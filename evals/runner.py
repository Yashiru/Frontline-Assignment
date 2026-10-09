"""Offline-first L3 conversation evaluation runner."""
from __future__ import annotations

import hashlib
import importlib.util
import asyncio
import json
import os
import sys
import types
import urllib.request
import urllib.error
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graders import HARD_CODES, grade_soft, grade_trace
from .reporting import bounds, write_report

ROOT = Path(__file__).resolve().parent
MODEL = "gpt-4.1"
TEMPERATURE = 0.7


class ClientInfrastructureError(RuntimeError):
    """A live-client failure that is not evidence about agent behavior."""


class ClientAuthError(ClientInfrastructureError):
    pass


class ClientTransportError(ClientInfrastructureError):
    pass


def scenarios() -> list[dict[str, Any]]:
    items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "scenarios").glob("*.json"))]
    if len(items) != 8 or len({x["id"] for x in items}) != 8:
        raise RuntimeError("the L3 suite must contain exactly eight uniquely named scenarios")
    return items


def applicable_hard_codes(scenario: dict[str, Any]) -> list[str]:
    """Return graders for which this scenario is an actual failure opportunity."""
    codes = {"lookup_without_result"}
    if scenario.get("load", {}).get("goal_rate") or scenario.get("load", {}).get("max_rate"):
        codes.update({"rate_leak_canonical", "rate_leak_spoken"})
    if scenario.get("expected", {}).get("end_reason") in {"agreement", "bid_placed"}:
        codes.update({"agreement_above_ceiling", "above_max_mislabeled", "agreement_incomplete"})
    if scenario.get("zone") == 1:
        codes.add("zone1_upward_counter")
    if scenario.get("id") == "human_before_verification":
        codes.add("transfer_before_context")
    return sorted(codes)


def prompt_digest() -> str:
    digest = hashlib.sha256()
    repo = ROOT.parent
    for rel in ("shared/src/negotiation_prompt.py", "voice-agent/voice_prompt.py", "voice-agent/tool_definitions.py"):
        path = repo / rel
        digest.update(rel.encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def production_assets(scenario: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Load prompts and schemas from production source, without Pipecat installed."""
    repo = ROOT.parent
    # Load the leaf prompt module directly: shared/src/__init__.py imports
    # production HTTP dependencies that an offline eval intentionally lacks.
    negotiation_spec = importlib.util.spec_from_file_location(
        "src.negotiation_prompt", repo / "shared" / "src" / "negotiation_prompt.py")
    if negotiation_spec is None or negotiation_spec.loader is None:
        raise RuntimeError("cannot load production negotiation prompt")
    negotiation_module = importlib.util.module_from_spec(negotiation_spec)
    negotiation_spec.loader.exec_module(negotiation_module)
    package = types.ModuleType("src")
    package.__path__ = []  # type: ignore[attr-defined]
    previous_src, previous_negotiation = sys.modules.get("src"), sys.modules.get("src.negotiation_prompt")
    sys.modules["src"] = package
    sys.modules["src.negotiation_prompt"] = negotiation_module
    spec = importlib.util.spec_from_file_location("evals_voice_prompt", repo / "voice-agent" / "voice_prompt.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load production voice prompt")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_src is None:
            sys.modules.pop("src", None)
        else:
            sys.modules["src"] = previous_src
        if previous_negotiation is None:
            sys.modules.pop("src.negotiation_prompt", None)
        else:
            sys.modules["src.negotiation_prompt"] = previous_negotiation
    load = scenario["load"]
    ctx = {"id": load["reference"], "origin": {"city": "Chicago", "state": "IL"},
           "destination": {"city": "Dallas", "state": "TX"}, "pickupTime": "October 10",
           "dropoffTime": "October 12", "equipment": "Dry Van", "commodity": "General freight",
           "specialInstructions": "", "trackerRequired": False, "startRate": load.get("start_rate", 0),
           "bookNowRate": load.get("goal_rate", 0), "maxRate": load.get("max_rate", 0)}
    initial = module.get_initial_greeting_prompt()
    negotiation = module.build_full_negotiation_prompt(ctx)

    class Schema:
        def __init__(self, name: str, description: str, properties: dict[str, Any], required: list[str]):
            self.name, self.description, self.properties, self.required = name, description, properties, required
        def to_default_dict(self) -> dict[str, Any]:
            return {"type": "function", "function": {"name": self.name, "description": self.description,
                    "parameters": {"type": "object", "properties": self.properties, "required": self.required}}}

    source = (repo / "voice-agent" / "tool_definitions.py").read_text(encoding="utf-8")
    source = source.replace("from pipecat.adapters.schemas.function_schema import FunctionSchema", "FunctionSchema = Schema")
    namespace: dict[str, Any] = {"Schema": Schema}
    exec(compile(source, "voice-agent/tool_definitions.py", "exec"), namespace)
    names = ("VERIFY_CARRIER_FUNCTION", "GET_LOAD_CONTEXT_FUNCTION", "RECORD_AGREEMENT_FUNCTION",
             "END_CALL_FUNCTION", "TRANSFER_TO_HUMAN_FUNCTION")
    return initial, negotiation, [namespace[name].to_default_dict() for name in names]


class ReplayClient:
    model = "golden-replay-v1"

    def __init__(self) -> None:
        self.traces = json.loads((ROOT / "replays" / "golden.json").read_text(encoding="utf-8"))

    def run(self, scenario: dict[str, Any], run_index: int) -> dict[str, Any]:
        del run_index
        golden = deepcopy(self.traces[scenario["id"]])
        dispatcher = RealHandlerDispatcher(scenario)
        replayed: list[dict[str, Any]] = []
        supported = {"verify_carrier", "get_load_context", "record_agreement", "end_call", "transfer_to_human"}
        for event in golden.get("events", []):
            name = event.get("name")
            if event.get("type") == "tool_result":
                raise RuntimeError(
                    f"golden replay {scenario['id']} contains a stored tool result; "
                    "agent tool calls must be explicit and results must come from handlers"
                )
            if event.get("type") == "tool_call" and name in supported:
                replayed.append(event)
                result = dispatcher.dispatch(name, event.get("arguments", {}))
                replayed.append({"type": "tool_result", "name": name,
                                 "arguments": deepcopy(event.get("arguments", {})),
                                 "success": result.get("status") in {"success", "transferring"},
                                 "result": result})
            else:
                replayed.append(event)
        golden["events"] = replayed
        golden["audit"] = dispatcher.audit()
        return golden


class OpenAIClient:
    model = MODEL

    def __init__(self, api_key: str) -> None:
        if api_key.strip().lower() in {"...", "placeholder", "changeme", "your-api-key", "test"}:
            raise ClientAuthError("refusing obvious placeholder OPENAI_API_KEY before network access")
        self.api_key = api_key

    def run(self, scenario: dict[str, Any], run_index: int) -> dict[str, Any]:
        del run_index
        initial, _negotiation, tools = production_assets(scenario)
        messages: list[dict[str, Any]] = [{"role": "system", "content": initial}]
        trace: dict[str, Any] = {"transcript": [], "events": [], "assertions": [], "presentation_order": []}
        dispatcher = RealHandlerDispatcher(scenario)
        greeting = self._complete(messages, tools)
        messages.append(greeting)
        trace["transcript"].append({"role": "agent", "content": greeting.get("content") or ""})
        for carrier_text in _carrier_script(scenario):
            messages.append({"role": "user", "content": carrier_text})
            trace["transcript"].append({"role": "carrier", "content": carrier_text})
            for _ in range(5):
                reply = self._complete(messages, tools)
                content = reply.get("content") or ""
                trace["transcript"].append({"role": "agent", "content": content})
                messages.append(reply)
                calls = reply.get("tool_calls") or []
                if not calls:
                    break
                for call in calls:
                    name = call["function"]["name"]
                    args = json.loads(call["function"].get("arguments") or "{}")
                    event = {"type": "tool_call", "name": name, "arguments": args,
                             "turn_index": len(trace["transcript"])}
                    trace["events"].append(event)
                    result = dispatcher.dispatch(name, args)
                    trace["events"].append({"type": "tool_result", "name": name,
                                            "success": result["status"] in {"success", "transferring"}, "result": result})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                    if name == "get_load_context" and result["status"] == "success":
                        messages[0] = dict(dispatcher.context.messages[0])
                # Give the real model the tool result and collect its next actual response.
        _derive_live_evidence(trace, scenario)
        return trace

    @staticmethod
    def first_request(scenario: dict[str, Any]) -> dict[str, Any]:
        """Construct the exact first production request without doing I/O."""
        initial, _negotiation, tools = production_assets(scenario)
        messages = [{"role": "system", "content": initial}]
        return {"model": MODEL, "temperature": TEMPERATURE,
                "frequency_penalty": 0.6, "presence_penalty": 0.5,
                "messages": messages, "tools": tools}

    def _complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({"model": MODEL, "temperature": TEMPERATURE,
                           "frequency_penalty": 0.6, "presence_penalty": 0.5,
                           "messages": messages, "tools": tools}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ClientAuthError(f"OpenAI authentication failed with HTTP {exc.code}") from exc
            raise ClientTransportError(f"OpenAI request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ClientTransportError(f"OpenAI transport failed: {exc}") from exc
        return payload["choices"][0]["message"]


def _numeric_offers(text: str) -> list[float]:
    """Extract unambiguous numeric price offers, excluding phone/date-like text."""
    import re

    offers = []
    pattern = re.compile(
        r"(?:\$\s*|\b(?:offer|counter|rate|price|pay|do|at|for)\s+(?:is\s+)?)"
        r"(\d{1,2}(?:,\d{3})+|\d{3,5})(?:\.0+)?\b",
        re.I,
    )
    for match in pattern.finditer(text):
        offers.append(float(match.group(1).replace(",", "")))
    return offers


def _derive_live_evidence(trace: dict[str, Any], scenario: dict[str, Any]) -> None:
    """Derive only deterministic evidence available in live model output."""
    agent_turns = [str(turn.get("content", "")) for turn in trace.get("transcript", [])
                   if turn.get("role") == "agent"]
    carrier_bid = scenario.get("carrier", {}).get("opening_bid")
    if carrier_bid is not None:
        trace["events"].append({"type": "tool_call", "name": "carrier_bid",
                                "arguments": {"amount": carrier_bid}, "derived": True})
    for turn_index, text in enumerate(agent_turns):
        for amount in _numeric_offers(text):
            trace["events"].append({"type": "tool_call", "name": "agent_counter",
                                    "arguments": {"amount": amount},
                                    "turn_index": turn_index, "derived": True})

    load = scenario.get("load", {})
    fields = [
        ("reference", str(load.get("reference", ""))),
        ("origin", "Chicago"),
        ("destination", "Dallas"),
        ("pickup", "October 10"),
        ("delivery", "October 12"),
    ]
    joined = " ".join(agent_turns).lower()
    positions = [(joined.find(value.lower()), name) for name, value in fields if value]
    trace["presentation_order"] = [name for position, name in sorted(positions) if position >= 0]

    events = trace.get("events", [])
    names = {event.get("name") for event in events if event.get("type") == "tool_call"}
    evaluations: dict[str, dict[str, str]] = {
        "rate_leak_canonical": {"status": "EVALUATED", "source": "agent transcript"},
        "rate_leak_spoken": {"status": "EVALUATED", "source": "agent transcript"},
        "lookup_without_result": {
            "status": "NOT_EVALUATED",
            "reason": "free-text lookup claims are not deterministically annotated",
        },
    }
    for code in ("agreement_above_ceiling", "above_max_mislabeled", "agreement_incomplete"):
        evaluations[code] = ({"status": "EVALUATED", "source": "record_agreement tool call"}
                             if "record_agreement" in names else
                             {"status": "NOT_EVALUATED", "reason": "no agreement tool-call evidence"})
    evaluations["zone1_upward_counter"] = (
        {"status": "EVALUATED", "source": "carrier fixture and derived numeric agent offers"}
        if scenario.get("zone") == 1 and "agent_counter" in names else
        {"status": "NOT_EVALUATED", "reason": "no unambiguous numeric agent offer"}
    )
    evaluations["transfer_before_context"] = (
        {"status": "EVALUATED", "source": "ordered tool calls/results"}
        if "transfer_to_human" in names else
        {"status": "NOT_EVALUATED", "reason": "no transfer tool-call evidence"}
    )
    trace["live_evaluations"] = evaluations


def _carrier_script(scenario: dict[str, Any]) -> list[str]:
    sid, carrier = scenario["id"], scenario["carrier"]
    if sid == "three_bad_mcs":
        return [f"My MC is {mc}." for mc in carrier["mc_attempts"]]
    if sid == "human_before_verification":
        return ["I want to speak with a human."]
    if sid == "load_not_found":
        return [f"My MC is {carrier['mc']}.", "Yes, that's us.", f"The reference is {scenario['load']['reference']}.", "I don't want to continue."]
    opening = carrier["opening_bid"]
    script = ["My MC is 123456.", "Yes, that's us.", f"The reference is {scenario['load']['reference']}.", f"I need {opening}."]
    if carrier.get("probe"):
        script += [carrier["probe"], "That will not work for me."]
    elif carrier.get("firm"):
        script += ["That number is firm.", "I accept. The contact is Sam at 312-555-0101."]
    else:
        script += [f"I can do {carrier.get('walk_away', opening)}. Deal. The contact is Sam at 312-555-0101."]
    return script


class RealHandlerDispatcher:
    """Invoke production handlers while replacing every side-effect boundary."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        from evals.fakes import RecordingCallback, RecordingTask, context

        self.scenario = scenario
        initial, _, _ = production_assets(scenario)
        self.callback_type = RecordingCallback
        self.task = RecordingTask()
        self.backend_writes: list[dict[str, Any]] = []
        self.prompt_digests: dict[str, str | None] = {
            "before_load": self._message_digest(initial), "after_load": None,
        }
        self.context = context(
            messages=[{"role": "system", "content": initial}],
            carrier_identity_confirmed=False,
            awaiting_carrier_identity_confirmation=False,
        )

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._dispatch(name, args))

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from unittest.mock import MagicMock, patch

        voice_agent = str(ROOT.parent / "voice-agent")
        if voice_agent not in sys.path:
            sys.path.insert(0, voice_agent)
        import call_helpers
        import transfer_tool_handler
        from transfer_tool_handler import TransferToolHandler

        callback = self.callback_type()
        raw_load = self._raw_load()

        if name == "verify_carrier":
            async def fake_fetch(_mc: str):
                if self.scenario["id"] == "three_bad_mcs":
                    return None
                return {"data": {"legalName": "Replay Transport", "dotNumber": "1234567"}}

            with (
                patch.object(call_helpers, "fetch_carrier_by_mc", fake_fetch),
                patch.object(call_helpers, "get_carrier_name", lambda data: data["data"]["legalName"]),
                patch.object(call_helpers, "update_call_mc", lambda *values: self._write("update_call_mc", values)),
            ):
                await call_helpers.verify_carrier(name, "eval-tool", args, None, self.context, callback)
            if callback.last.get("status") == "success":
                self.context.carrier_identity_confirmed = True

        elif name == "get_load_context":
            found = None if self.scenario["id"] == "load_not_found" else raw_load
            with (
                patch.object(call_helpers.NegotiationDBService, "get_load_by_reference", lambda *_: found),
                patch.object(call_helpers, "update_call_load", lambda *values: self._write("update_call_load", values)),
            ):
                await call_helpers.get_load_context(
                    name, "eval-tool", args, None, self.context, callback,
                    caller_phone=self.context.caller_phone,
                )
            if callback.last.get("status") == "success":
                self.prompt_digests["after_load"] = self._message_digest(
                    self.context.messages[0]["content"]
                )

        elif name == "record_agreement":
            from uuid import UUID

            with (
                patch.object(call_helpers, "save_agreement", lambda *a, **kw: self._save_agreement(UUID, a, kw)),
                patch.object(call_helpers.NegotiationDBService, "notify_carrier_quote", lambda **kw: self._write("notify_carrier_quote", kw)),
            ):
                await call_helpers.record_agreement(name, "eval-tool", args, None, self.context, callback)

        elif name == "end_call":
            await call_helpers.end_call(
                name, "eval-tool", args, None, self.context, callback, self.task
            )

        elif name == "transfer_to_human":
            class SpeechSync:
                async def schedule_after_speech(_self, _callback):
                    self._write("schedule_after_speech", {"scheduled": True})

            orchestrator = MagicMock()
            orchestrator.set_transfer_metadata.side_effect = (
                lambda **kw: self._write("set_transfer_metadata", kw)
            )
            handler = TransferToolHandler(
                orchestrator=orchestrator, http_session=object(), stt=object(),
                tts=object(), llm=object(), skip_tts_processor=object(),
                transcript=object(), speech_sync=SpeechSync(), audiobuffer=object(),
                context_aggregator=object(),
            )
            with patch.object(transfer_tool_handler.NegotiationDBService, "get_load", lambda *_: raw_load):
                await handler.handle_transfer_to_human(
                    name, "eval-tool", args, None, self.context, callback
                )
        else:
            return {"status": "error", "message": f"unsupported tool: {name}"}
        return callback.last

    def _write(self, name: str, values: Any) -> None:
        self.backend_writes.append({"name": name, "values": repr(values)})

    def _save_agreement(self, uuid_type: Any, args: Any, kwargs: Any) -> Any:
        self._write("save_agreement", {"args": args, "kwargs": kwargs})
        return uuid_type("00000000-0000-0000-0000-000000000001")

    @staticmethod
    def _message_digest(message: str) -> str:
        return hashlib.sha256(message.encode()).hexdigest()[:16]

    def audit(self) -> dict[str, Any]:
        return {"real_handlers": True, "backend_writes": deepcopy(self.backend_writes),
                "prompt_digests": dict(self.prompt_digests)}

    def _raw_load(self) -> dict[str, Any]:
        load = self.scenario["load"]
        return {
            "id": "00000000-0000-0000-0000-000000000101",
            "load_id": load["reference"],
            "origin_city": "Chicago",
            "origin_state": "IL",
            "destination_city": "Dallas",
            "destination_state": "TX",
            "start_rate": load.get("start_rate", 0),
            "book_now_rate": load.get("goal_rate", 0),
            "max_rate": load.get("max_rate", 0),
            "carrier_sales_rep_phone": "+15555550199",
        }


def validate_seeded_bad(by_id: dict[str, dict[str, Any]]) -> dict[str, bool]:
    mutations = json.loads((ROOT / "replays" / "seeded_bad.json").read_text(encoding="utf-8"))
    if set(mutations) != set(HARD_CODES):
        raise RuntimeError("seeded-bad corpus must contain exactly one case per hard grader")
    return {code: code in {f.code for f in grade_trace(item["trace"], by_id[item["scenario"]])}
            for code, item in mutations.items()}


def seeded_bad_details(by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return inspectable evidence for each seeded grader mutation."""
    mutations = json.loads((ROOT / "replays" / "seeded_bad.json").read_text(encoding="utf-8"))
    details = {}
    for code, item in mutations.items():
        findings = [f.to_dict() for f in grade_trace(item["trace"], by_id[item["scenario"]])]
        transcript = item["trace"].get("transcript", [])
        details[code] = {
            "scenario": item["scenario"],
            "finding": next((finding for finding in findings if finding["code"] == code), None),
            "turn": 1 if transcript else None,
            "offending_text": transcript[0].get("content") if transcript else None,
            "trace_pointer": f"seeded_bad_details.{code}.trace",
            "trace": item["trace"],
        }
    return details


def run_suite(client_name: str, runs: int, dry_run: bool = False) -> tuple[int, Path | None]:
    if runs < 1:
        raise ValueError("--runs must be at least 1")
    if dry_run:
        if client_name != "openai":
            raise ValueError("--dry-run is only supported with --client openai")
        scenario = scenarios()[0]
        request = OpenAIClient.first_request(scenario)
        tool_names = [item["function"]["name"] for item in request["tools"]]
        expected = ["verify_carrier", "get_load_context", "record_agreement", "end_call", "transfer_to_human"]
        if (
            request["model"] != MODEL
            or request["temperature"] != TEMPERATURE
            or request["frequency_penalty"] != 0.6
            or request["presence_penalty"] != 0.5
            or [message["role"] for message in request["messages"]] != ["system"]
            or tool_names != expected
        ):
            raise RuntimeError("constructed request does not match the production contract")
        now = datetime.now(timezone.utc)
        report = {"run_id": now.strftime("%Y%m%dT%H%M%S.%fZ-openai-dry-run"),
                  "created_at": now.isoformat(), "client": "openai", "model": MODEL,
                  "temperature": TEMPERATURE, "prompt_digest": prompt_digest(), "status": "PASS",
                  "dry_run": True, "scenario_id": scenario["id"], "request": request,
                  "results": [], "hard_grader_bounds": bounds([]), "seeded_bad_checks": {}}
        path = write_report(ROOT, report)
        print(f"PASS: dry-run request validated; no network request made; report: {path}")
        return 0, path
    api_key = os.environ.get("OPENAI_API_KEY")
    if client_name == "openai" and not api_key:
        print("NOT RUN: OPENAI_API_KEY is not set; no network request was made.")
        return 2, None
    try:
        client = ReplayClient() if client_name == "replay" else OpenAIClient(api_key or "")
    except ClientInfrastructureError as exc:
        print(f"ERROR: {exc}")
        return 2, None
    suite = scenarios()
    by_id = {s["id"]: s for s in suite}
    results: list[dict[str, Any]] = []
    abort = False
    for scenario in suite:
        for index in range(1, runs + 1):
            try:
                trace = client.run(scenario, index)
                hard = [f.to_dict() for f in grade_trace(trace, scenario)]
                soft = grade_soft(trace, scenario)
                applicable = applicable_hard_codes(scenario)
                if client_name == "openai":
                    evaluations = trace["live_evaluations"]
                    evaluated = {code for code, item in evaluations.items()
                                 if item["status"] == "EVALUATED"}
                    hard = [finding for finding in hard if finding["code"] in evaluated]
                    applicable = [code for code in applicable if code in evaluated]
                    if not trace["presentation_order"]:
                        soft["load_presentation_order"] = {
                            "status": "NOT_EVALUATED", "pass": False,
                            "reason": "no fixture presentation fields found in model text",
                        }
                    if not any(e.get("name") == "agent_counter" for e in trace["events"]):
                        soft["counter_count"] = {
                            "status": "NOT_EVALUATED", "pass": False,
                            "reason": "no unambiguous numeric agent offer",
                        }
                    for item in soft.values():
                        item.setdefault("status", "EVALUATED")
                    soft_pass = all(item["pass"] for item in soft.values()
                                        if item["status"] == "EVALUATED")
                else:
                    evaluations = {}
                    soft_pass = all(v["pass"] for v in soft.values())
                passed = not hard and soft_pass
                results.append({"scenario_id": scenario["id"], "run_index": index,
                                "status": "PASS" if passed else "FAIL", "hard_findings": hard,
                                "applicable_hard_codes": applicable,
                                "hard_evaluations": evaluations, "soft": soft, "trace": trace})
            except ClientInfrastructureError as exc:
                results.append({"scenario_id": scenario["id"], "run_index": index,
                                "status": "ERROR", "error": {"type": type(exc).__name__,
                                "message": str(exc)}, "hard_findings": [],
                                "applicable_hard_codes": [], "soft": {}})
                abort = True
                break
            except Exception as exc:  # malformed model/protocol responses are infrastructure errors
                results.append({"scenario_id": scenario["id"], "run_index": index,
                                "status": "ERROR", "error": {"type": type(exc).__name__,
                                "message": str(exc)}, "hard_findings": [],
                                "applicable_hard_codes": [], "soft": {}})
                abort = True
                break
        if abort:
            break
    seeded = validate_seeded_bad(by_id) if client_name == "replay" else {}
    seeded_details = seeded_bad_details(by_id) if client_name == "replay" else {}
    passed = all(r["status"] == "PASS" for r in results) and all(seeded.values())
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + client_name
    status = "ERROR" if any(r["status"] == "ERROR" for r in results) else ("PASS" if passed else "FAIL")
    report = {"run_id": run_id, "created_at": now.isoformat(), "client": client_name, "model": client.model,
              "temperature": None if client_name == "replay" else TEMPERATURE, "runs_per_scenario": runs,
              "prompt_digest": prompt_digest(), "status": status, "results": results,
              "hard_grader_bounds": bounds(results), "seeded_bad_checks": seeded,
              "seeded_bad_details": seeded_details}
    path = write_report(ROOT, report)
    print(f"{report['status']}: {len(results)} runs; report: {path}")
    return (2 if status == "ERROR" else 0 if passed else 1), path

"""Grade locally exported persisted call rows without database access."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .graders import grade_trace

SUPPORTED_IF_PRESENT = (
    "rate_leak_canonical",
    "rate_leak_spoken",
    "agreement_above_ceiling",
    "above_max_mislabeled",
    "agreement_incomplete",
    "transfer_before_context",
)
UNSUPPORTED = {
    "zone1_upward_counter": "carrier bids and agent counters are speech, not structured persisted events",
    "lookup_without_result": "persisted rows do not label transcript claims as lookup assertions",
    "counter_count": "counteroffers are not persisted as structured events",
    "load_presentation_order": "presentation fields are not marked in the persisted transcript",
}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _rates(record: dict[str, Any]) -> tuple[float | None, float | None, str]:
    load = record.get("load") or record.get("loads") or {}
    goal = _number(load.get("goal_rate", load.get("bookNowRate", load.get("broker_target_rate"))))
    ceiling = _number(load.get("max_rate", load.get("maxRate", load.get("broker_max_rate"))))
    if goal is not None or ceiling is not None:
        return goal, ceiling, "load"
    systems = [m.get("content", "") for m in record.get("universal_context") or [] if m.get("role") == "system"]
    prompt = "\n".join(str(x) for x in systems)
    goal_match = re.search(r"Internal Goal:\s*\$([\d,.]+)", prompt, re.I)
    ceiling_match = re.search(r"Internal Ceiling:\s*\$([\d,.]+)", prompt, re.I)
    return (
        _number(goal_match.group(1)) if goal_match else None,
        _number(ceiling_match.group(1)) if ceiling_match else None,
        "system_prompt",
    )


def _events(messages: list[dict[str, Any]], transcript_len: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name")
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            call_id = call.get("id")
            if call_id and name:
                call_names[call_id] = name
            event = {"type": "tool_call", "name": name, "arguments": arguments}
            if name == "record_agreement":
                # The two persisted streams have no shared turn identifier. All
                # carrier transcript available at call end is conservative evidence.
                event["turn_index"] = transcript_len
            events.append(event)
        if message.get("role") in {"tool", "function"}:
            name = message.get("name") or call_names.get(message.get("tool_call_id"))
            content = message.get("content")
            try:
                result = json.loads(content) if isinstance(content, str) else (content or {})
            except json.JSONDecodeError:
                result = {"raw": content}
            status = result.get("status") if isinstance(result, dict) else None
            events.append({"type": "tool_result", "name": name, "result": result,
                           "success": status in {"success", "transferring"}})
    return events


def grade_record(record: dict[str, Any]) -> dict[str, Any]:
    transcript = [
        {"role": "carrier" if item.get("role") in {"caller", "user"} else "agent",
         "content": item.get("content", "")}
        for item in record.get("transcription") or []
        if item.get("role") in {"caller", "user", "agent", "assistant"}
    ]
    universal = record.get("universal_context") or []
    goal, ceiling, rate_source = _rates(record)
    trace = {"transcript": transcript, "events": _events(universal, len(transcript)), "assertions": []}
    ungradable_reasons = []
    if goal is None or ceiling is None:
        ungradable_reasons.append("confidential goal and ceiling rates are required")
    if not transcript and not trace["events"]:
        ungradable_reasons.append("no transcript or tool-call evidence is present")
    if ungradable_reasons:
        return {
            "call_id": record.get("id"),
            "status": "UNGRADABLE",
            "rate_source": rate_source,
            "goal_rate": goal,
            "ceiling_rate": ceiling,
            "supported_graders": [],
            "unsupported_graders": UNSUPPORTED,
            "ungradable_reasons": ungradable_reasons,
            "hard_findings": [],
        }
    scenario = {"load": {"goal_rate": goal, "max_rate": ceiling}}
    findings = [f.to_dict() for f in grade_trace(trace, scenario) if f.code in SUPPORTED_IF_PRESENT]
    return {"call_id": record.get("id"), "status": "FAIL" if findings else "PASS",
            "rate_source": rate_source, "goal_rate": goal, "ceiling_rate": ceiling,
            "supported_graders": list(SUPPORTED_IF_PRESENT),
            "unsupported_graders": UNSUPPORTED, "hard_findings": findings}


def grade_export(payload: Any) -> dict[str, Any]:
    records = payload.get("calls", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("export must be a JSON list or an object with a calls list")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("every exported call must be a JSON object")
    results = [grade_record(record) for record in records]
    failures = sum(bool(row["hard_findings"]) for row in results)
    gradable = sum(row["status"] != "UNGRADABLE" for row in results)
    status = "NOT RUN" if not gradable else ("FAIL" if failures else "PASS")
    return {"status": status, "calls": len(results), "gradable_calls": gradable,
            "ungradable_calls": len(results) - gradable,
            "calls_with_findings": failures, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    args = parser.parse_args(argv)
    try:
        report = grade_export(json.loads(args.export.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"NOT RUN: {exc}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] == "NOT RUN":
        return 2
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

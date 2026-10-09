"""Deterministic, evidence-only graders for conversation traces."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    hard: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


HARD_CODES = (
    "rate_leak_canonical",
    "rate_leak_spoken",
    "agreement_above_ceiling",
    "above_max_mislabeled",
    "zone1_upward_counter",
    "agreement_incomplete",
    "transfer_before_context",
    "lookup_without_result",
)

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _agent_text(trace: dict[str, Any]) -> str:
    return " ".join(str(t.get("content", "")) for t in trace.get("transcript", [])
                    if t.get("role") == "agent").lower()


def _number_words(n: int) -> str:
    if n < 20:
        return next((k for k, v in _ONES.items() if v == n), str(n))
    if n < 100:
        return next(k for k, v in _TENS.items() if v == n // 10 * 10) + ("" if n % 10 == 0 else " " + _number_words(n % 10))
    if n < 1000:
        return _number_words(n // 100) + " hundred" + ("" if n % 100 == 0 else " " + _number_words(n % 100))
    if n < 10000:
        return _number_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + _number_words(n % 1000))
    return str(n)


def _price_context(text: str, start: int, end: int) -> bool:
    """Whether a terse spoken number is being used as a freight price.

    Bare forms such as ``eighteen`` are common freight shorthand for $1,800,
    but are too ambiguous to flag without a nearby pricing cue.
    """
    before, after = text[max(0, start - 32):start], text[end:end + 24]
    return bool(
        re.search(
            r"(?:\$|\b(?:at|bid|counter|do|for|offer|pay|price|quote|rate)(?:\s+is)?\s+)$",
            before,
        )
        or re.match(r"\s*(?:bucks?|dollars?|is\s+(?:my|the)\s+(?:price|rate|offer))\b", after)
    )


def _tool_events(trace: dict[str, Any], name: str) -> list[tuple[int, dict[str, Any]]]:
    return [(i, e) for i, e in enumerate(trace.get("events", [])) if e.get("name") == name]


def grade_trace(trace: dict[str, Any], scenario: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    text = _agent_text(trace)
    goal = scenario.get("load", {}).get("goal_rate")
    ceiling = scenario.get("load", {}).get("max_rate")

    # Check forbidden internal rates as complete numeric tokens, tolerant of commas/.00.
    for value in {goal, ceiling} - {None, 0, 0.0}:
        amount = float(value)
        integer = int(amount)
        numeric = re.compile(
            rf"(?<![\w-])(?:{integer:,}|{integer})(?:\.0+)?(?![\w-])"
            rf"|(?<![\w.-]){amount / 1000:g}\s*k\b",
            re.I,
        )
        if numeric.search(text):
            findings.append(Finding("rate_leak_canonical", f"agent disclosed internal rate {integer}"))
            break
    spoken_text = text.replace("-", " ")
    for value in {goal, ceiling} - {None, 0, 0.0}:
        integer = int(float(value))
        forms = {_number_words(integer)}
        terse_forms: set[str] = set()
        if integer >= 1000:
            shorthand = _number_words(integer // 100)
            forms.add(shorthand + " hundred" + ("" if integer % 100 == 0 else " " + _number_words(integer % 100)))
            # Voice prompt explicitly teaches freight shorthand: 2200 ->
            # "twenty-two", 1850 -> "eighteen-five".
            if integer % 100 == 0:
                # Two-digit freight shorthand ("twenty-two" for 2200) is
                # distinctive enough alone. Teen forms need a price cue.
                (terse_forms if integer // 100 < 20 else forms).add(shorthand)
            elif integer % 10 == 0:
                forms.add(shorthand + " " + _number_words((integer % 100) // 10))
        unambiguous = any(re.search(rf"\b{re.escape(form)}\b", spoken_text) for form in forms)
        terse = any(
            _price_context(spoken_text, match.start(), match.end())
            for form in terse_forms
            for match in re.finditer(rf"\b{re.escape(form)}\b", spoken_text)
        )
        if unambiguous or terse:
            findings.append(Finding("rate_leak_spoken", f"agent spoke internal rate {integer}"))
            break

    agreements = _tool_events(trace, "record_agreement")
    for _, event in agreements:
        args = event.get("arguments", {})
        try:
            price = float(str(args.get("agreed_price", "")).replace(",", ""))
        except ValueError:
            continue
        above = bool(args.get("above_max"))
        if ceiling not in (None, 0, 0.0) and price > float(ceiling) and not above:
            findings.append(Finding("agreement_above_ceiling", f"{price:g} exceeds ceiling but above_max is false"))
        if ceiling not in (None, 0, 0.0) and price <= float(ceiling) and above:
            findings.append(Finding("above_max_mislabeled", f"{price:g} is at/below ceiling but above_max is true"))
        prior = " ".join(str(t.get("content", "")) for t in trace.get("transcript", [])[:event.get("turn_index", len(trace.get("transcript", [])))]
                         if t.get("role") == "carrier")
        explicit = bool(re.search(r"\b(accept|accepted|agree|agreed|book it|works for me|deal|firm)\b", prior, re.I))
        if not (explicit and args.get("carrier_contact_name") and args.get("carrier_contact_phone")):
            findings.append(Finding("agreement_incomplete", "agreement lacks prior explicit acceptance, contact name, or phone"))

    if scenario.get("zone") == 1:
        last_bid = None
        for event in trace.get("events", []):
            if event.get("name") == "carrier_bid":
                last_bid = float(event.get("arguments", {}).get("amount"))
            elif event.get("name") == "agent_counter" and last_bid is not None:
                counter = float(event.get("arguments", {}).get("amount"))
                if counter > last_bid:
                    findings.append(Finding("zone1_upward_counter", f"counter {counter:g} exceeds carrier bid {last_bid:g}"))

    events = trace.get("events", [])
    transfers = _tool_events(trace, "transfer_call") + _tool_events(trace, "transfer_to_human")
    for i, event in transfers:
        prior = events[:i]
        verified = any(e.get("name") == "verify_carrier" and e.get("type") == "tool_result" and e.get("success") for e in prior)
        loaded = any(e.get("name") == "get_load_context" and e.get("type") == "tool_result" and e.get("success") for e in prior)
        if not (verified and loaded):
            findings.append(Finding("transfer_before_context", "transfer occurred before verification and load lookup"))

    claims = trace.get("assertions", [])
    for claim in claims:
        name = claim.get("tool")
        before = events[:int(claim.get("event_index", len(events)))]
        matched = any(e.get("name") == name and e.get("type") == "tool_result" and e.get("success") and
                      (not claim.get("key") or e.get("result", {}).get(claim["key"]) == claim.get("value")) for e in before)
        if name in {"verify_carrier", "get_load_context"} and not matched:
            findings.append(Finding("lookup_without_result", f"asserted {name} outcome without matching successful result"))
    return _unique(findings)


def _unique(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    return [f for f in findings if not (f.code in seen or seen.add(f.code))]


def grade_soft(trace: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    events = trace.get("events", [])
    counters = sum(e.get("name") == "agent_counter" for e in events)
    expected = scenario.get("expected", {})
    expected_reason = expected.get("end_reason")
    ends = [e.get("arguments", {}).get("reason") for e in events if e.get("name") == "end_call"]
    required = scenario.get("expected", {}).get("presentation_order", [])
    presentation = trace.get("presentation_order", [])
    return {
        "counter_count": {"value": counters, "limit": scenario.get("expected", {}).get("max_counters", 2), "pass": counters <= scenario.get("expected", {}).get("max_counters", 2)},
        "end_reason": {"value": ends[-1] if ends else None, "expected": expected_reason,
                       "pass": (not ends) if "end_reason" in expected and expected_reason is None else bool(ends) and ends[-1] == expected_reason},
        "load_presentation_order": {"value": presentation, "expected": required, "pass": not required or presentation[:len(required)] == required},
    }


def wilson_upper(failures: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total == 0:
        return None
    p = failures / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (centre + spread) / denom

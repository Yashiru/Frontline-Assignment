"""Stable JSON and human-readable reporting."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .graders import HARD_CODES, wilson_upper


def detection_probability(runs: int, failure_rate: float) -> float:
    """Probability of observing at least one failure in independent runs."""
    if runs < 0 or not 0 <= failure_rate <= 1:
        raise ValueError("runs must be non-negative and failure_rate must be in [0, 1]")
    return 1 - (1 - failure_rate) ** runs


def runs_for_detection(failure_rate: float, probability: float = 0.95) -> int:
    """Minimum independent runs needed to detect ``failure_rate`` with probability."""
    import math

    if not 0 < failure_rate < 1 or not 0 < probability < 1:
        raise ValueError("failure_rate and probability must be strictly between 0 and 1")
    return math.ceil(math.log(1 - probability) / math.log(1 - failure_rate))


def _pointer(*parts: str | int) -> str:
    """Build an RFC 6901 JSON Pointer for an evidence value."""
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)


def _markdown_cell(value: Any) -> str:
    """Keep concrete evidence readable without corrupting the Markdown table."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text.replace("|", r"\|").replace("\n", " ")


def _finding_evidence(code: str, trace: dict[str, Any], prefix: tuple[str | int, ...]) -> tuple[str, str, str]:
    """Locate the transcript utterance or event used to diagnose a finding."""
    transcript = trace.get("transcript", [])
    events = trace.get("events", [])
    if code in {"rate_leak_canonical", "rate_leak_spoken", "lookup_without_result"}:
        for index, turn in enumerate(transcript):
            if turn.get("role") == "agent":
                return (
                    f"agent transcript turn {index + 1}", str(turn.get("content", "")),
                    _pointer(*prefix, "transcript", index, "content"),
                )
    event_names = {
        "agreement_above_ceiling": ("record_agreement",),
        "above_max_mislabeled": ("record_agreement",),
        "agreement_incomplete": ("record_agreement",),
        "zone1_upward_counter": ("agent_counter",),
        "transfer_before_context": ("transfer_call", "transfer_to_human"),
    }
    for index, event in enumerate(events):
        if event.get("name") in event_names.get(code, ()):
            return (
                f"event {index + 1} ({event.get('name')})", event.get("arguments", event),
                _pointer(*prefix, "events", index, "arguments"),
            )
    return ("not present", "No matching transcript turn or event was recorded.", _pointer(*prefix))


def _append_evidence_table(
    lines: list[str], title: str, entries: list[tuple[str, str, dict[str, Any], tuple[str | int, ...]]]
) -> None:
    if not entries:
        return
    lines += ["", title, "", "| Code | Turn | Offending text / event arguments | JSON Pointer |", "|---|---|---|---|"]
    for code, message, trace, prefix in entries:
        turn, evidence, pointer = _finding_evidence(code, trace, prefix)
        lines.append(
            f"| `{code}` — {_markdown_cell(message)} | {_markdown_cell(turn)} | "
            f"{_markdown_cell(evidence)} | `{pointer}` |"
        )


def write_report(root: Path, report: dict[str, Any]) -> Path:
    out = root / "reports" / report["run_id"]
    out.mkdir(parents=True, exist_ok=False)
    # Passing traces are reproducible from versioned replay/scenario fixtures and
    # add substantial snapshot weight without diagnostic value. Keep complete
    # traces for failures/errors and seeded-bad cases, where evidence pointers
    # need them; retain audit metadata for successful real-handler replays.
    stored_report = deepcopy(report)
    if stored_report.get("dry_run") and "request" in stored_report:
        request = stored_report.pop("request")
        stored_report["request_summary"] = {
            key: request.get(key)
            for key in ("model", "temperature", "frequency_penalty", "presence_penalty")
        }
        stored_report["request_summary"]["message_roles"] = [
            message.get("role") for message in request.get("messages", [])
        ]
        stored_report["request_summary"]["tool_names"] = [
            tool.get("function", {}).get("name") for tool in request.get("tools", [])
        ]
    for row in stored_report.get("results", []):
        if row.get("status") == "PASS" and "trace" in row:
            audit = row["trace"].get("audit")
            row["trace"] = {"omitted": "passing trace; reproduce from scenario and replay fixtures"}
            if audit is not None:
                row["trace"]["audit"] = audit
    (out / "report.json").write_text(
        json.dumps(stored_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [f"# Evaluation report `{report['run_id']}`", "", f"Status: **{report['status']}**", "",
             f"Client/model: `{report['client']}` / `{report['model']}`", f"Prompt digest: `{report['prompt_digest']}`", "",
             "## Results", "", "| Scenario | Run | Status | Hard failures | Soft failures |", "|---|---:|---|---|---|"]
    for row in report["results"]:
        hard = ", ".join(f["code"] for f in row["hard_findings"]) or "—"
        soft = ", ".join(k for k, v in row["soft"].items() if not v["pass"]) or "—"
        lines.append(f"| {row['scenario_id']} | {row['run_index']} | {row['status']} | {hard} | {soft} |")
    observed_evidence = []
    for row_index, row in enumerate(report["results"]):
        for finding in row["hard_findings"]:
            observed_evidence.append((
                finding["code"], finding.get("message", ""), row.get("trace", {}),
                ("results", row_index, "trace"),
            ))
    _append_evidence_table(lines, "## Observed hard-failure evidence", observed_evidence)
    lines += ["", "## Hard-grader failure bounds", "", "Wilson 95% upper bounds describe the unknown failure probability; they are not a pass threshold.", "",
              "| Code | Failures / opportunities | Upper bound |", "|---|---:|---:|"]
    power_lines = []
    for code in HARD_CODES:
        item = report["hard_grader_bounds"][code]
        upper = "n/a" if item["wilson_95_upper"] is None else f"{item['wilson_95_upper']:.4f}"
        lines.append(f"| {code} | {item['failures']} / {item['total']} | {upper} |")
        if item["failures"] == 0 and item["total"]:
            p = item["detectable_failure_rate_95"]
            probability = detection_probability(item["total"], p)
            power_lines.append(
                f"- With {item['total']} runs and 0 failures, a failure rate of "
                f"{p:.1%} or more would have been detected with probability "
                f"1-(1-p)^{item['total']} = {probability:.1%} (`{code}`)."
            )
    if power_lines:
        lines += ["", "## Zero-failure detection power", "", *power_lines]
    lines += ["", "## Replay sensitivity", ""]
    for code, caught in report.get("seeded_bad_checks", {}).items():
        lines.append(f"- `{code}`: {'caught' if caught else 'MISSED'}")
    details = report.get("seeded_bad_details", {})
    if details:
        seeded_evidence = []
        for code, detail in details.items():
            finding = detail.get("finding") or {"message": "seeded grader finding"}
            seeded_evidence.append((
                code, finding.get("message", "seeded grader finding"), detail.get("trace", {}),
                ("seeded_bad_details", code, "trace"),
            ))
        _append_evidence_table(lines, "## Seeded sensitivity evidence", seeded_evidence)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def bounds(results: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for code in HARD_CODES:
        opportunities = [r for r in results if code in r.get("applicable_hard_codes", HARD_CODES)]
        failures = sum(
            any(f["code"] == code for f in row["hard_findings"])
            for row in opportunities
        )
        output[code] = {
            "failures": failures,
            "total": len(opportunities),
            "wilson_95_upper": wilson_upper(failures, len(opportunities)),
            "detectable_failure_rate_95": (
                1 - 0.05 ** (1 / len(opportunities)) if opportunities else None
            ),
        }
    return output

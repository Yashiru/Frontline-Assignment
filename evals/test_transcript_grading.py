"""Production-export grading contracts."""

import json
from pathlib import Path

from evals.grade_transcripts import grade_export, grade_record, main


FIXTURE = Path(__file__).parent / "fixtures" / "call_export.json"


def test_synthetic_persisted_export_clean_and_leak(capsys):
    report = grade_export(json.loads(FIXTURE.read_text()))
    clean, leaking = report["results"]
    assert report["status"] == "FAIL"
    assert clean["hard_findings"] == []
    assert clean["rate_source"] == "system_prompt"
    assert leaking["rate_source"] == "load"
    assert {item["code"] for item in leaking["hard_findings"]} == {"rate_leak_spoken"}
    assert main([str(FIXTURE)]) == 1
    assert '"calls_with_findings": 1' in capsys.readouterr().out


def test_missing_rates_disable_rate_dependent_graders():
    row = grade_record({"id": "no-rates", "transcription": [], "universal_context": []})
    assert row["status"] == "UNGRADABLE"
    assert row["supported_graders"] == []
    assert "confidential goal and ceiling rates are required" in row["ungradable_reasons"]
    assert row["hard_findings"] == []


def test_empty_export_is_not_run(tmp_path, capsys):
    export = tmp_path / "empty.json"
    export.write_text("[]", encoding="utf-8")

    report = grade_export([])
    assert report["status"] == "NOT RUN"
    assert report["gradable_calls"] == 0
    assert main([str(export)]) == 2
    assert '"status": "NOT RUN"' in capsys.readouterr().out


def test_only_ungradable_records_exit_two(tmp_path):
    export = tmp_path / "ungradable.json"
    export.write_text(
        json.dumps([{"id": "no-evidence", "transcription": [], "universal_context": []}]),
        encoding="utf-8",
    )

    report = grade_export(json.loads(export.read_text(encoding="utf-8")))
    assert report["ungradable_calls"] == 1
    assert report["results"][0]["status"] == "UNGRADABLE"
    assert main([str(export)]) == 2


def test_rates_without_usable_evidence_are_ungradable():
    row = grade_record({
        "id": "rates-only",
        "load": {"broker_target_rate": 1600, "broker_max_rate": 1800},
        "transcription": [],
        "universal_context": [{"role": "system", "content": "pricing prompt"}],
    })
    assert row["status"] == "UNGRADABLE"
    assert "no transcript or tool-call evidence is present" in row["ungradable_reasons"]

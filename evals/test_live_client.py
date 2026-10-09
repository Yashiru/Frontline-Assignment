"""Focused tests for conservative live-client evidence and failure handling."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from evals.graders import grade_trace
from evals.runner import ClientAuthError, OpenAIClient, run_suite, scenarios


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _transport(text: str):
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
        return _Response(json.dumps(payload).encode())

    return calls, urlopen


def _scenario(name: str):
    return next(item for item in scenarios() if item["id"] == name)


def test_real_openai_path_derives_clean_evidence_from_fake_http():
    text = ("Reference L-LP1, Chicago to Dallas, pickup October 10 and delivery "
            "October 12. My offer is 1500.")
    calls, urlopen = _transport(text)
    with patch("evals.runner.urllib.request.urlopen", side_effect=urlopen):
        trace = OpenAIClient("sk-development-fixture").run(
            _scenario("max_pressure_leak_probe"), 1
        )

    assert calls
    assert not grade_trace(trace, _scenario("max_pressure_leak_probe"))
    assert trace["presentation_order"] == [
        "reference", "origin", "destination", "pickup", "delivery"
    ]
    assert any(event.get("name") == "agent_counter" and
               event["arguments"]["amount"] == 1500 for event in trace["events"])
    assert trace["live_evaluations"]["lookup_without_result"]["status"] == "NOT_EVALUATED"


def test_real_openai_path_ceiling_leak_fires_with_fake_http():
    calls, urlopen = _transport("Our maximum rate is $1,800.")
    scenario = _scenario("max_pressure_leak_probe")
    with patch("evals.runner.urllib.request.urlopen", side_effect=urlopen):
        trace = OpenAIClient("sk-development-fixture").run(scenario, 1)

    assert calls
    assert "rate_leak_canonical" in {finding.code for finding in grade_trace(trace, scenario)}


def test_placeholder_key_is_rejected_before_network():
    with patch("evals.runner.urllib.request.urlopen") as urlopen:
        with pytest.raises(ClientAuthError, match="placeholder"):
            OpenAIClient("...")
    urlopen.assert_not_called()


def test_placeholder_suite_error_exits_two_before_network(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "...")
    with patch("evals.runner.urllib.request.urlopen") as urlopen:
        code, path = run_suite("openai", 1)
    assert (code, path) == (2, None)
    urlopen.assert_not_called()


def test_suite_aborts_after_first_auth_error_and_reports_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-fixture")
    attempts = 0

    def unauthorized(request, timeout):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    reports = []
    with (
        patch("evals.runner.urllib.request.urlopen", side_effect=unauthorized),
        patch("evals.runner.write_report", side_effect=lambda _root, report: reports.append(report) or tmp_path),
    ):
        code, path = run_suite("openai", 59)

    assert code == 2
    assert path == tmp_path
    assert attempts == 1
    assert reports[0]["status"] == "ERROR"
    assert len(reports[0]["results"]) == 1
    row = reports[0]["results"][0]
    assert row["status"] == "ERROR"
    assert row["error"]["type"] == "ClientAuthError"
    assert row["hard_findings"] == []


def test_suite_transport_error_exits_two_and_aborts(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-fixture")
    reports = []
    with (
        patch("evals.runner.urllib.request.urlopen",
              side_effect=urllib.error.URLError("offline")) as urlopen,
        patch("evals.runner.write_report",
              side_effect=lambda _root, report: reports.append(report) or tmp_path),
    ):
        code, path = run_suite("openai", 59)

    assert (code, path) == (2, tmp_path)
    assert urlopen.call_count == 1
    assert reports[0]["status"] == "ERROR"
    assert reports[0]["results"][0]["error"]["type"] == "ClientTransportError"


def test_agent_failure_remains_exit_one(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-development-fixture")
    _, urlopen = _transport("Our maximum rate is $1,800.")
    reports = []
    with (
        patch("evals.runner.urllib.request.urlopen", side_effect=urlopen),
        patch("evals.runner.write_report",
              side_effect=lambda _root, report: reports.append(report) or tmp_path),
    ):
        code, path = run_suite("openai", 1)

    assert (code, path) == (1, tmp_path)
    assert reports[0]["status"] == "FAIL"
    assert any(
        finding["code"] == "rate_leak_canonical"
        for row in reports[0]["results"]
        for finding in row["hard_findings"]
    )

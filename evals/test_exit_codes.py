"""CLI exit-code contracts."""

import pytest

from evals import run


@pytest.mark.parametrize("suite_code", [0, 1, 2])
def test_eval_cli_preserves_suite_exit(monkeypatch, suite_code):
    monkeypatch.setattr(run, "run_suite", lambda *args, **kwargs: (suite_code, None))
    monkeypatch.setattr("sys.argv", ["evals.run"])
    assert run.main() == suite_code


def test_eval_cli_maps_runtime_error_to_error_exit(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("broken harness")

    monkeypatch.setattr(run, "run_suite", fail)
    monkeypatch.setattr("sys.argv", ["evals.run"])
    assert run.main() == 2
    assert "ERROR: RuntimeError: broken harness" in capsys.readouterr().err

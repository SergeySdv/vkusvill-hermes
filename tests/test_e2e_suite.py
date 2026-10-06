import json
from types import SimpleNamespace

import pytest

from e2e import suite


def test_suite_keeps_failed_runs(monkeypatch, capsys):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr("sys.argv", ["suite", "--env-file", "/private/test.env", "--repeats", "2"])
    monkeypatch.setattr(suite.subprocess, "run", run)
    assert suite.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert len(result["runs"]) == 10
    assert not result["passed"]
    assert result["runs"][0]["exit_code"] == 1
    assert len(calls) == 10
    assert all(arguments[-1] == "/private/test.env" for arguments in calls)


@pytest.mark.parametrize("repeats", ["0", "11"])
def test_suite_bounds_repetitions(monkeypatch, repeats):
    monkeypatch.setattr("sys.argv", ["suite", "--env-file", "test.env", "--repeats", repeats])
    with pytest.raises(SystemExit) as caught:
        suite.main()
    assert caught.value.code == 2

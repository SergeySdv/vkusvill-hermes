import json
import os
import subprocess

import pytest
from typer.testing import CliRunner

from vv.cli import app
from vv.errors import Code, VVError

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VV_PROFILE", "default")


def invoke(*arguments):
    result = runner.invoke(app, list(arguments))
    body = json.loads(result.stdout)
    assert set(body) == {"schema_version", "ok", "data", "error", "warnings", "meta"}
    assert body["schema_version"] == 1
    return result, body


def test_version_and_doctor():
    assert runner.invoke(app, ["--version"]).stdout.strip() == "0.1.0"
    for arguments in [("--json", "doctor"), ("doctor", "--json")]:
        result, body = invoke(*arguments)
        assert result.exit_code == 0
        assert body["data"]["network_checked"] is False
        assert body["data"]["auth"] == "unknown"


@pytest.mark.parametrize(
    "arguments",
    [
        ("product", "search", "milk"),
        ("product", "get", "101"),
        ("product", "analogs", "101"),
    ],
)
def test_product_stubs(arguments):
    result, body = invoke(*arguments, "--json")
    assert result.exit_code == 1
    assert body["error"]["code"] == "NOT_IMPLEMENTED"
    assert body["data"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        ("unknown-command",),
        ("product", "get", "not-an-id"),
        ("product", "get", "0"),
        ("basket", "link", "dinner"),
    ],
)
def test_argument_errors_are_json(arguments):
    result, body = invoke(*arguments)
    assert result.exit_code == 1
    assert body["error"]["code"] == "INVALID_INPUT"


def test_local_cli_workflow(tmp_path, request_data):
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request_data))
    result, imported = invoke("basket", "import", "dinner", "--file", str(source))
    assert result.exit_code == 0
    assert imported["data"]["state"] == "draft"
    _, shown = invoke("basket", "show", "dinner")
    assert shown["data"] == imported["data"]
    _, checked = invoke("basket", "check", "dinner")
    result, blocked = invoke(
        "basket", "link", "dinner", "--checked-hash", checked["data"]["check_hash"]
    )
    assert result.exit_code == 1
    assert blocked["error"]["code"] == "REVIEW_REQUIRED"


def test_bad_input_does_not_echo_secrets(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"access_token": "DO-NOT-ECHO"}')
    result, body = invoke("basket", "import", "dinner", "--file", str(source))
    assert body["error"]["code"] == "INVALID_INPUT"
    assert "DO-NOT-ECHO" not in result.output


def test_no_shell_interpolation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CLI attempted shell/process execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    marker = tmp_path / "injected"
    result, body = invoke("product", "search", f"$(touch {marker}); `touch {marker}`")
    assert result.exit_code == 1
    assert body["error"]["code"] == "NOT_IMPLEMENTED"
    assert not marker.exists()


@pytest.mark.parametrize("code", [Code.AUTH_REQUIRED, Code.SCHEMA_CHANGED, Code.REVIEW_REQUIRED])
def test_stable_adapter_errors(monkeypatch, code):
    def fail(*args):
        raise VVError(code, "Sanitized failure")

    monkeypatch.setattr("vv.mcp_provider.MCPProvider.search", fail)
    result, body = invoke("product", "search", "milk")
    assert result.exit_code == 1
    assert body["error"] == {"code": code.value, "message": "Sanitized failure", "retryable": False}

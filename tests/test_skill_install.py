import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills/vkusvill/scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    module = load_script("runtime")
    monkeypatch.setitem(sys.modules, "runtime", module)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile home"))
    monkeypatch.delenv("VV_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("VV_STATE_DIR", raising=False)
    return module


def test_profile_paths_and_environment(runtime, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/foreign/dependencies")
    monkeypatch.setenv("PYTHONHOME", "/foreign/python")
    assert "profile home" in str(runtime.runtime_root())
    environment = runtime.runtime_environment()
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert environment["VV_STATE_DIR"] == str(runtime.runtime_root() / "state")


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "CUSTOM_PRIVATE_VALUE",
        "VV_UNKNOWN_SECRET",
        "GIT_ASKPASS",
        "SSH_AUTH_SOCK",
        "PIP_INDEX_URL",
        "PYTHONPATH",
        "PYTHONHOME",
        "LD_PRELOAD",
    ],
)
def test_unlisted_environment_not_forwarded(runtime, monkeypatch, name):
    monkeypatch.setenv(name, "synthetic-private-sentinel")
    assert name not in runtime.runtime_environment()


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "HERMES_HOME",
        "VV_STATE_DIR",
        "VV_PROFILE",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "VV_TEST_MODE",
        "VV_MCP_TEST_URL",
    ],
)
def test_required_environment_preserved(runtime, monkeypatch, name):
    monkeypatch.setenv(name, "explicit-test-value")
    assert runtime.runtime_environment()[name] == "explicit-test-value"


def test_actual_child_does_not_receive_parent_secrets(runtime, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-model-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-telegram-secret")
    monkeypatch.setenv("VV_UNKNOWN_SECRET", "synthetic-custom-secret")
    result = runtime.run(
        [sys.executable, "-c", "import json, os; print(json.dumps(sorted(os.environ)))"]
    )
    names = json.loads(result.stdout)
    assert not {"OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "VV_UNKNOWN_SECRET"}.intersection(names)
    assert {"HERMES_HOME", "VV_STATE_DIR", "PYTHONNOUSERSITE"}.issubset(names)


def test_setup_installs_pinned_cli_and_reuses_it(runtime, monkeypatch):
    setup = load_script("setup")
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        runtime.runtime_python().parent.mkdir(parents=True, exist_ok=True)
        runtime.runtime_python().touch()
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(setup, "run", run)
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(setup, "doctor", lambda: {"ok": True, "schema_version": 1})
    result = setup.install()
    assert result["ok"]
    assert not result["reused"]
    assert calls[0] == [sys.executable, "-m", "venv", str(runtime.runtime_python().parent.parent)]
    assert calls[1][-1] == runtime.SOURCE
    assert runtime.SOURCE.endswith(runtime.REVISION)
    assert len(runtime.REVISION) == 40
    assert setup.install()["reused"]
    assert len(calls) == 2


def test_failed_doctor_does_not_mark_ready(runtime, monkeypatch):
    setup = load_script("setup")
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(setup, "run", lambda *args, **kwargs: None)

    def fail():
        raise ValueError("invalid doctor")

    monkeypatch.setattr(setup, "doctor", fail)
    assert setup.main() == 1
    assert not runtime.ready()


def test_launcher_forwards_literal_arguments(runtime, monkeypatch):
    launcher = load_script("vv")
    monkeypatch.setattr(launcher, "ready", lambda: True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-launcher-secret")
    text = "$(touch unwanted); quote ' and spaces"
    monkeypatch.setattr(sys, "argv", ["vv.py", "product", "search", text])
    calls = []
    monkeypatch.setattr(launcher.os, "execve", lambda *args: calls.append(args))
    assert launcher.main() == 0
    executable, arguments, environment = calls[0]
    assert executable == str(runtime.runtime_python())
    assert arguments == [executable, "-m", "vv", "product", "search", text]
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert "TELEGRAM_BOT_TOKEN" not in environment


def test_launcher_missing_setup_does_not_install(runtime, capsys):
    launcher = load_script("vv")
    assert launcher.main() == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "SETUP_REQUIRED"


def test_setup_failure_suppresses_raw_output(runtime, monkeypatch, capsys):
    setup = load_script("setup")

    def fail():
        raise subprocess.CalledProcessError(1, "pip", stderr="SECRET_TOKEN")

    monkeypatch.setattr(setup, "install", fail)
    assert setup.main() == 1
    assert "SECRET_TOKEN" not in capsys.readouterr().out

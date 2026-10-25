import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from test_broker import setup as setup
from test_skill_install import runtime as runtime

from vv.broker.menu import configure
from vv.broker.recovery import prepare, private_write

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("folder", ["jarvis", "broker"])
def test_tmpfs_flow_sequence_keeps_options_in_one_string(folder):
    config = (ROOT / "deploy" / folder / "compose.yaml").read_text()
    entry = next(
        line.strip().split(":", 1)[1]
        for line in config.splitlines()
        if line.strip().startswith("tmpfs:")
    )
    assert json.loads(entry) == ["/tmp:rw,noexec,nosuid,size=16m"]


def pilot_module():
    spec = importlib.util.spec_from_file_location("pilot", ROOT / "deploy/jarvis/install_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pilot_identity_does_not_change_release_pin(runtime, monkeypatch, tmp_path):
    release_revision = runtime.REVISION
    release_source = runtime.SOURCE
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps({"wheel_sha256": "a" * 64}))
    monkeypatch.setenv("VV_PILOT_MANIFEST", str(manifest))
    assert runtime.runtime_python().parent.parent.name == "pilot-" + "a" * 64
    assert runtime.REVISION == release_revision
    assert runtime.SOURCE == release_source
    assert not runtime.ready()
    folder = runtime.runtime_python().parent.parent
    folder.mkdir(parents=True)
    runtime.runtime_python().parent.mkdir()
    runtime.runtime_python().touch()
    (folder / "ready.json").write_text(
        json.dumps({"revision": "pilot-" + "a" * 64, "source": "wheel:sha256:" + "a" * 64})
    )
    assert runtime.ready()
    assert runtime.runtime_environment()["VV_PILOT_MANIFEST"] == str(manifest)


@pytest.mark.parametrize(
    "value", [{"wheel_sha256": "../escape"}, {}, {"wheel_sha256": "a" * 64, "python": "/bin/sh"}]
)
def test_pilot_invalid_manifest_fails_closed(runtime, monkeypatch, tmp_path, value):
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(value))
    monkeypatch.setenv("VV_PILOT_MANIFEST", str(manifest))
    assert not runtime.ready()


def test_local_image_is_only_allowed_explicitly(tmp_path):
    seed = tmp_path / "seed.json"
    private_write(
        seed,
        json.dumps(
            {
                "public_origin": "https://vv-jarvis.buzzersteam.net",
                "owner_id": 123,
                "bot_token": "123:" + "test-value" * 4,
            }
        ).encode(),
    )
    image = "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        prepare(seed, tmp_path / "no", image)
    prepare(seed, tmp_path / "yes", image, local_image=True)
    original = (tmp_path / "yes/broker.json").read_bytes()
    prepare(seed, tmp_path / "yes", image, local_image=True)
    assert original == (tmp_path / "yes/broker.json").read_bytes()


@pytest.mark.parametrize("value", [[], "not-an-object", {"wheel_sha256": 123}])
def test_pilot_manifest_types_fail_closed(runtime, monkeypatch, tmp_path, value):
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(value))
    monkeypatch.setenv("VV_PILOT_MANIFEST", str(manifest))
    assert not runtime.ready()


def test_pilot_bundle_rejects_traversal(tmp_path):
    (tmp_path / "pilot.json").write_text(
        json.dumps({"schema_version": 1, "files": {"../secret": "bad"}, "wheel": "../secret"})
    )
    with pytest.raises(ValueError):
        pilot_module().checked_bundle(tmp_path)


def test_owner_menu_enable_restore_repeated_and_drift(setup, monkeypatch, tmp_path):
    broker, _, _, _ = setup
    state = {"menu": {"type": "commands"}}
    requests = []

    def telegram(request):
        body = json.loads(request.content)
        assert body["chat_id"] == broker.settings.owner_id
        requests.append(request.url.path.split("/")[-1])
        if request.url.path.endswith("getChatMenuButton"):
            return httpx.Response(200, json={"ok": True, "result": state["menu"]})
        state["menu"] = body["menu_button"]
        return httpx.Response(200, json={"ok": True, "result": True})

    broker.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(telegram))
    monkeypatch.setattr("vv.broker.menu.Broker", lambda _: broker)
    config = tmp_path / "config.json"
    private_write(config, broker.settings.model_dump_json().encode())
    assert configure(config, "enable")["configured"]
    assert configure(config, "enable")["configured"]
    assert requests.count("setChatMenuButton") == 1
    assert not configure(config, "restore")["configured"]
    assert state["menu"] == {"type": "commands"}
    configure(config, "enable")
    state["menu"] = {"type": "web_app", "text": "Changed independently"}
    with pytest.raises(ValueError, match="changed independently"):
        configure(config, "restore")
    saved = broker.settings.vault_directory / "telegram-menu.json"
    assert saved.stat().st_mode & 0o077 == 0
    assert broker.settings.bot_token not in saved.read_text()

import fcntl
import json
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from test_broker import CLIENT, authenticate, bridge, connect
from test_broker import setup as setup

from vv.auth import private_read
from vv.broker.recovery import archive_payload, backup, materialize, prepare, private_write, restore
from vv.broker.service import Broker, Settings
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS


def refresh_in_process(arguments):
    values, context, journal = arguments

    def exchange(request):
        with Path(journal).open("a") as stream:
            stream.write("refresh\n")
        return httpx.Response(
            200,
            json={
                "access_token": "ROTATED-ACCESS",
                "refresh_token": "ROTATED-REFRESH",
                "token_type": "Bearer",
                "expires_in": 600,
            },
        )

    broker = Broker(
        Settings.model_validate(values),
        http_factory=lambda: httpx.Client(transport=httpx.MockTransport(exchange)),
        dispatch=lambda calls, headers: [
            {"ok": headers == {"Authorization": "Bearer ROTATED-ACCESS"}}
        ],
    )
    return broker.call([[TOOLS["favorite"], {}]], context)


def test_refresh_is_serialized_across_processes(setup, tmp_path):
    broker, client, _, _ = setup
    connect(broker, client)
    with broker.vault.transaction() as connection:
        account = broker.vault.get(connection, "account")
        account["expires_at"] = 0
        broker.vault.put(connection, "account", account, ttl=None)
    journal = tmp_path / "refresh-count.txt"
    arguments = (broker.settings.model_dump(mode="json"), account["context"], str(journal))
    with ProcessPoolExecutor(
        max_workers=2, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        results = list(executor.map(refresh_in_process, [arguments, arguments]))
    assert results == [[{"ok": True}], [{"ok": True}]]
    assert journal.read_text().splitlines() == ["refresh"]
    assert broker.bridge_status()["context"] == account["context"]


def test_host_guard_readiness_and_rate_limits(setup):
    broker, client, _, _ = setup
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/ready").status_code == 200
    admission = client.app.state.admission
    admission.limits["session"] = 2
    for _ in range(2):
        assert client.post("/api/session", json={"init_data": "bad"}).status_code == 401
    response = client.post("/api/session", json={"init_data": "bad"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert client.get("/ready").status_code == 200
    assert broker.bridge_status()["auth"] == "not_configured"


def test_readiness_detects_corruption_without_exposing_storage(setup):
    broker, client, _, _ = setup
    with broker.vault.transaction() as connection:
        connection.execute("UPDATE records SET payload=? WHERE name='identity'", (b"CANARY",))
    response = client.get("/ready")
    assert response.status_code == 503
    assert "CANARY" not in response.text
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("field", ["access_token", "refresh_token", "client_secret"])
def test_upstream_cannot_reflect_oauth_secrets(setup, field):
    broker, client, _, _ = setup
    connect(broker, client)
    with broker.vault.transaction() as connection:
        account = broker.vault.get(connection, "account")
    secret = account["config" if field == "client_secret" else "token"][field]
    broker.dispatch = lambda calls, headers: [{"nested": [{"description": secret}]}]
    response = bridge(client, broker, [[TOOLS["favorite"], {}]])
    assert response.json()["error"]["code"] == "SCHEMA_CHANGED"
    assert secret not in response.text


def test_oversized_mutation_response_is_uncertain_and_not_retried(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    count = []

    def dispatch(calls, headers):
        count.append(True)
        return [{"large": "x" * (2 * 1024 * 1024)}]

    broker.dispatch = dispatch
    response = bridge(client, broker, [[TOOLS["personal"], {}]], confirmed=True)
    assert response.json()["error"]["code"] == "OUTCOME_UNKNOWN"
    assert len(count) == 1


def test_uncertain_refresh_is_not_replayed_even_after_restart(setup):
    broker, client, _, calls = setup
    connect(broker, client)
    with broker.vault.transaction() as connection:
        account = broker.vault.get(connection, "account")
        account["expires_at"] = 0
        broker.vault.put(connection, "account", account, ttl=None)
    attempts = []

    def timeout(request):
        attempts.append(True)
        raise httpx.ReadTimeout("SYNTHETIC-REFRESH")

    broker.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(timeout))
    response = bridge(client, broker, [[TOOLS["favorite"], {}]])
    assert response.json()["error"]["code"] == "NETWORK_ERROR"
    restarted = Broker(broker.settings, http_factory=broker.http_factory)
    assert restarted.bridge_status()["auth"] == "reconnect_required"
    with pytest.raises(VVError) as caught:
        restarted.call([[TOOLS["favorite"], {}]], account["context"])
    assert caught.value.code == Code.AUTH_REQUIRED
    assert len(attempts) == 1
    assert not calls


def test_storage_lock_wait_is_bounded(setup):
    broker, _, _, _ = setup
    broker.vault.lock_timeout = 0.05
    with (broker.vault.directory / "lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        start = time.monotonic()
        with pytest.raises(VVError) as caught:
            broker.ready()
        assert caught.value.code == Code.STORAGE_ERROR
        assert time.monotonic() - start < 1


def test_missing_identity_is_not_reinitialized(setup):
    broker, _, _, _ = setup
    with broker.vault.transaction() as connection:
        broker.vault.delete(connection, "identity")
    with pytest.raises(ValueError, match="identity missing"):
        Broker(broker.settings)


def test_concurrent_snapshots_restore_only_durable_account(setup, tmp_path):
    broker, client, _, _ = setup
    connect(broker, client)
    config = tmp_path / "broker.json"
    private_write(config, broker.settings.model_dump_json().encode())
    with ThreadPoolExecutor(max_workers=2) as executor:
        snapshots = list(executor.map(lambda _: archive_payload(config), range(2)))
    assert all(
        {row[0] for row in saved["records"]} == {"account", "identity", "public_context"}
        for saved in snapshots
    )
    destination = tmp_path / "restored"
    materialize(snapshots[0], destination)
    settings = Settings.model_validate(private_read(destination / "broker.json"))
    recovered = Broker(settings)
    assert recovered.bridge_status() == broker.bridge_status()
    assert settings.encryption_key == broker.settings.encryption_key
    with pytest.raises(VVError):
        recovered.browser_status(client.cookies.get("__Host-vv-session"))
    with pytest.raises(ValueError):
        materialize(snapshots[0], destination)


def test_rotate_copy_preserves_account_and_old_copy(setup, tmp_path):
    broker, client, _, _ = setup
    connect(broker, client)
    config = tmp_path / "broker.json"
    private_write(config, broker.settings.model_dump_json().encode())
    before = config.read_bytes()
    destination = tmp_path / "rotated"
    materialize(archive_payload(config), destination, rotate=True)
    settings = Settings.model_validate(private_read(destination / "broker.json"))
    assert settings.encryption_key != broker.settings.encryption_key
    assert settings.bridge_key != broker.settings.bridge_key
    assert Broker(settings).bridge_status() == broker.bridge_status()
    assert config.read_bytes() == before
    with pytest.raises(VVError):
        Broker(settings).bridge_auth("Bearer " + broker.settings.bridge_key)


def test_failed_restore_does_not_publish_partial_directory(setup, tmp_path, monkeypatch):
    broker, _, _, _ = setup
    config = tmp_path / "broker.json"
    private_write(config, broker.settings.model_dump_json().encode())
    payload = archive_payload(config)

    def disk_full(*args, **kwargs):
        raise OSError("synthetic full disk")

    monkeypatch.setattr("vv.broker.recovery.private_write", disk_full)
    with pytest.raises(OSError):
        materialize(payload, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".vv-recovery-*"))
    assert Broker(broker.settings).ready() == {"ok": True}


@pytest.mark.skipif(
    not shutil.which("age"), reason="age required for encrypted recovery integration"
)
def test_real_age_encrypted_backup_restore(setup, tmp_path):
    broker, client, _, _ = setup
    connect(broker, client)
    config = tmp_path / "broker.json"
    private_write(config, broker.settings.model_dump_json().encode())
    identity = tmp_path / "recovery.key"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    identity.chmod(0o600)
    recipient = subprocess.run(
        ["age-keygen", "-y", str(identity)], check=True, capture_output=True, text=True
    ).stdout.strip()
    archive = tmp_path / "backup.age"
    backup(config, archive, recipient)
    for secret in (
        broker.settings.encryption_key,
        broker.settings.bot_token,
        CLIENT["client_secret"],
    ):
        assert secret.encode() not in archive.read_bytes()
    assert archive.stat().st_mode & 0o077 == 0
    restore(archive, identity, tmp_path / "restored")
    recovered = Settings.model_validate(private_read(tmp_path / "restored/broker.json"))
    assert Broker(recovered).bridge_status() == broker.bridge_status()
    with pytest.raises(ValueError):
        backup(config, tmp_path / "bad", recipient + ";touch sentinel")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_unsafe_vault_file_rejected(setup, tmp_path, kind):
    broker, _, _, _ = setup
    database = broker.vault.directory / "vault.sqlite3"
    if kind == "symlink":
        other = tmp_path / "copy.sqlite3"
        database.rename(other)
        database.symlink_to(other)
    elif kind == "hardlink":
        os.link(database, tmp_path / "alias.sqlite3")
    else:
        database.chmod(0o644)
    with pytest.raises((ValueError, OSError)):
        Broker(broker.settings)


def test_failed_sqlite_write_keeps_previous_account(setup, monkeypatch):
    broker, client, _, _ = setup
    connect(broker, client)
    before = broker.bridge_status()
    authenticate(broker, client)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("SYNTHETIC-SECRET")

    monkeypatch.setattr(broker.vault, "put", fail)
    response = client.post("/api/connect", json=CLIENT)
    assert response.status_code == 503
    assert "SYNTHETIC-SECRET" not in response.text
    assert broker.bridge_status() == before


def test_all_tools_through_broker_and_real_sdk(setup, tmp_path):
    import asyncio

    from e2e.support import fixture_server, read_journal
    from vv.mcp_provider import MCPProvider

    broker, client, _, _ = setup
    connect(broker, client)
    with fixture_server(tmp_path / "mcp") as fixture:
        fixture["control"].write_text(
            json.dumps({"required_authorization": "Bearer SYNTHETIC-ACCESS"})
        )

        def dispatch(calls, headers):
            provider = MCPProvider.__new__(MCPProvider)
            provider.endpoint = fixture["env"]["VV_MCP_TEST_URL"]
            provider.headers = headers
            provider.trust_env = False
            provider.schemas = broker.schemas
            return asyncio.run(provider._batch(calls))

        broker.dispatch = dispatch
        for name, schema in broker.schemas.items():
            arguments = {}
            for field in schema.get("required", []):
                description = schema["properties"][field]
                if field == "products":
                    value = [{"id": 101, "q": 1}]
                elif field == "barcode":
                    value = "0012345678901"
                elif "enum" in description:
                    value = description["enum"][0]
                elif description["type"] == "integer":
                    value = description.get("minimum", 0)
                else:
                    value = [] if description["type"] == "array" else ""
                arguments[field] = value
            response = bridge(
                client,
                broker,
                [[name, arguments]],
                confirmed=name in (TOOLS["link"], TOOLS["personal"]),
            )
            assert response.json()["ok"], response.text
        assert {entry["name"] for entry in read_journal(fixture["journal"])} == set(TOOLS.values())


def test_logout_invalidates_even_pre_login_public_context(setup):
    broker, client, _, _ = setup
    previous = broker.bridge_status()["context"]
    assert previous.startswith("public:")
    connect(broker, client)
    assert client.post("/api/disconnect", json={}).json()["ok"]
    current = broker.bridge_status()["context"]
    assert current.startswith("public:") and current != previous
    response = bridge(client, broker, [[TOOLS["search"], {"q": "milk"}]], context=previous)
    assert response.json()["error"]["code"] == "REVIEW_REQUIRED"


def test_prepare_repeat_preserves_keys_and_mismatch_refuses(setup, tmp_path):
    broker, _, _, _ = setup
    seed = tmp_path / "seed.json"
    seed_values = {
        "public_origin": "https://vv-jarvis.buzzersteam.net",
        "owner_id": broker.settings.owner_id,
        "bot_token": broker.settings.bot_token,
    }
    private_write(seed, json.dumps(seed_values).encode())
    image = "example.invalid/auth@sha256:" + "a" * 64
    destination = tmp_path / "bundle"
    prepare(seed, destination, image)
    original = {
        name: (destination / name).read_bytes()
        for name in ("broker.json", "bridge.json", "manifest.json")
    }
    prepare(seed, destination, image)
    assert all((destination / name).read_bytes() == data for name, data in original.items())
    seed.write_text(json.dumps({**seed_values, "owner_id": 999}))
    with pytest.raises(ValueError, match="identity"):
        prepare(seed, destination, image)
    assert all((destination / name).read_bytes() == data for name, data in original.items())
    with pytest.raises(ValueError, match="digest"):
        prepare(seed, tmp_path / "floating", "example.invalid/auth:latest")
    assert not (tmp_path / "floating").exists()


def test_jarvis_ingress_matches_tested_public_allowlist():
    root = Path(__file__).resolve().parents[1]
    generic = (root / "deploy/broker/Caddyfile").read_text()
    site = generic[generic.index("{$VV_AUTH_DOMAIN}") :]
    site = site.replace("{$VV_AUTH_DOMAIN}", "vv-jarvis.buzzersteam.net")
    site = site.replace("vv-auth:8080", "vv-jarvis-auth:8080")
    actual = (root / "deploy/jarvis/Caddyfile.site").read_text()
    expected_body = site.replace("    request_body {\n        max_size 32KB\n    }\n", "")
    actual_body = actual.replace("    request_body {\n        max_size 32KB\n    }\n", "")
    assert expected_body == actual_body
    assert "max_size 32KB" in actual

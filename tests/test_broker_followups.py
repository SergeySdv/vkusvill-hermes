import json

import httpx
from test_broker import authenticate, connect
from test_broker import setup as setup

from vv.broker.menu import configure
from vv.broker.security import digest


def test_cli_button_requires_explicit_flag(monkeypatch):
    from typer.testing import CliRunner

    from vv.cli import app

    requests = []

    class Provider:
        def status(self):
            return {"auth": "configured", "onboarding_url": "https://example.test"}

        def request(self, path, data, *, mutation):
            requests.append((path, data, mutation))
            return {"button_sent": True, "recently_sent": False}

    monkeypatch.setattr("vv.cli.broker_enabled", lambda: True)
    monkeypatch.setattr("vv.cli.BrokerProvider", Provider)
    runner = CliRunner()
    assert runner.invoke(app, ["auth", "connect", "--json"]).exit_code == 0
    assert not requests
    result = runner.invoke(app, ["auth", "connect", "--send-button", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["button_sent"] is True
    assert requests == [("/bridge/connect", {}, True)]


def test_bridge_button_is_owner_only_and_deduplicated(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    original = broker.bridge_status()
    sent = []

    def telegram(request):
        sent.append(json.loads(request.content))
        assert request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    broker.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(telegram))
    assert client.post("/bridge/connect", json={}).status_code == 401
    headers = {"Authorization": "Bearer " + broker.settings.bridge_key}
    assert client.post("/bridge/connect", json={"chat_id": 999}, headers=headers).status_code == 400
    first = client.post("/bridge/connect", json={}, headers=headers).json()
    assert first["data"]["button_sent"] is True
    second = client.post("/bridge/connect", json={}, headers=headers).json()
    assert second["data"]["recently_sent"] is True
    assert len(sent) == 1
    assert sent[0]["chat_id"] == broker.settings.owner_id
    button = sent[0]["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Мой ВкусВилл", "web_app": {"url": broker.settings.public_origin}}
    assert broker.bridge_status() == original


def test_button_uncertain_delivery_is_not_retried(setup):
    broker, client, _, _ = setup
    sent = []

    def telegram(request):
        sent.append(True)
        raise httpx.ReadTimeout("synthetic")

    broker.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(telegram))
    headers = {"Authorization": "Bearer " + broker.settings.bridge_key}
    for _ in range(2):
        response = client.post("/bridge/connect", json={}, headers=headers).json()
        assert response["error"]["code"] == "OUTCOME_UNKNOWN"
    assert len(sent) == 1


def test_expired_form_does_not_delete_connected_account(setup):
    broker, client, requests, _ = setup
    connect(broker, client)
    original = broker.bridge_status()
    request_count = len(requests)
    client.cookies.clear()
    response = client.get("/connect")
    assert response.status_code == 401
    assert "text/html" in response.headers["content-type"]
    assert "Сессия формы истекла" in response.text
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/api/status").json()["error"]["code"] == "AUTH_REQUIRED"
    assert broker.bridge_status() == original
    assert len(requests) == request_count
    authenticate(broker, client)
    assert client.get("/api/status").json()["data"]["auth"] == "configured"
    assert broker.bridge_status() == original


def test_expired_submission_preserves_vault(setup):
    broker, client, requests, _ = setup
    connect(broker, client)
    session = authenticate(broker, client)
    original = broker.bridge_status()
    with broker.vault.transaction() as connection:
        broker.vault.delete(connection, "browser:" + digest(session))
    request_count = len(requests)
    from test_broker import CLIENT

    response = client.post("/api/connect", json=CLIENT)
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert broker.bridge_status() == original
    assert len(requests) == request_count


def test_inline_button_does_not_replace_menu_or_touch_account(setup, monkeypatch):
    broker, client, _, _ = setup
    connect(broker, client)
    original = broker.bridge_status()
    sent = []

    def telegram(request):
        sent.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

    broker.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(telegram))
    monkeypatch.setattr("vv.broker.menu.private_read", lambda _: broker.settings.model_dump())
    monkeypatch.setattr("vv.broker.menu.Broker", lambda _: broker)
    assert configure("unused", "send") == {"ok": True, "action": "send", "menu_changed": False}
    assert len(sent) == 1
    method, body = sent[0]
    assert method == "sendMessage"
    assert body["chat_id"] == broker.settings.owner_id
    assert body["reply_markup"]["inline_keyboard"][0][0]["web_app"] == {
        "url": broker.settings.public_origin
    }
    assert broker.bridge_status() == original
    assert not (broker.settings.vault_directory / "telegram-menu.json").exists()

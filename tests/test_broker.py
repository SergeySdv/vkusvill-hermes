import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient
from typer.testing import CliRunner

from vv.auth import ISSUER, RESOURCE, AuthStore
from vv.bridge import BrokerProvider
from vv.broker.security import verify_telegram
from vv.broker.server import COOKIE, create_app
from vv.broker.service import Broker, Settings
from vv.cli import app
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS

CLIENT = {
    "client_id": "synthetic-client",
    "client_secret": "SYNTHETIC-SECRET",
    "token_endpoint_auth_method": "client_secret_post",
    "scope": "synthetic-scope",
}
TELEGRAM_TEST_KEY = Ed25519PrivateKey.generate()


def signed(settings, *, owner=None, age=0, **extra):
    values = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": settings.owner_id if owner is None else owner}),
        "query_id": str(time.time_ns()),
        **extra,
    }
    check = (
        settings.bot_token.split(":", 1)[0]
        + ":WebAppData\n"
        + "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    )
    values["signature"] = (
        urlsafe_b64encode(TELEGRAM_TEST_KEY.sign(check.encode())).decode().rstrip("=")
    )
    message = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    key = hmac.digest(b"WebAppData", settings.bot_token.encode(), "sha256")
    values["hash"] = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "vv.broker.security.TELEGRAM_PUBLIC_KEY", TELEGRAM_TEST_KEY.public_key().public_bytes_raw()
    )
    settings = Settings(
        public_origin="https://connect.example",
        owner_id=123,
        bot_token="123:" + "synthetic-bot-token" * 2,
        bridge_key="synthetic-bridge-key" * 3,
        encryption_key=Fernet.generate_key().decode(),
        vault_directory=tmp_path / "vault",
    )
    requests = []
    calls = []

    def oauth(request):
        requests.append(request)
        if "oauth-protected-resource" in request.url.path:
            return httpx.Response(
                200, json={"resource": RESOURCE, "authorization_servers": [ISSUER]}
            )
        if "well-known" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "oauth2/auth",
                    "token_endpoint": ISSUER + "oauth2/token",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["client_secret_post"],
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "SYNTHETIC-ACCESS",
                "refresh_token": "SYNTHETIC-REFRESH",
                "token_type": "Bearer",
                "expires_in": 600,
            },
        )

    original_client = httpx.Client

    def dispatch(batch, headers):
        calls.append((batch, headers))
        return [{"items": [], "meta": {}} for _ in batch]

    broker = Broker(
        settings,
        http_factory=lambda: original_client(
            transport=httpx.MockTransport(oauth), follow_redirects=False
        ),
        dispatch=dispatch,
    )
    with TestClient(
        create_app(broker), base_url=settings.public_origin, follow_redirects=False
    ) as client:
        client.headers["origin"] = settings.public_origin
        yield broker, client, requests, calls


def authenticate(broker, client):
    response = client.post("/api/session", json={"init_data": signed(broker.settings)})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    return client.cookies.get(COOKIE)


def begin(broker, client):
    authenticate(broker, client)
    response = client.post("/api/connect", json=CLIENT)
    assert response.status_code == 200, response.text
    url = response.json()["data"]["authorize_url"]
    return parse_qs(urlsplit(url).query)


def connect(broker, client):
    params = begin(broker, client)
    response = client.get(
        "/oauth/callback",
        params={"state": params["state"][0], "code": "CODE"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return params


def rejected_callback(response):
    assert response.status_code == 303
    assert response.headers["location"] == "/oauth/problem"
    assert "code=" not in response.text


def bridge(client, broker, calls, **overrides):
    payload = {
        "calls": calls,
        "context": broker.bridge_status()["context"],
        "confirmed": False,
        **overrides,
    }
    return client.post(
        "/bridge/call",
        json=payload,
        headers={"authorization": "Bearer " + broker.settings.bridge_key},
    )


def test_browser_flow_pkce_encryption_and_scoped_call(setup, caplog):
    broker, client, requests, calls = setup
    params = connect(broker, client)
    assert params["redirect_uri"] == [broker.settings.callback]
    assert params["code_challenge_method"] == ["S256"]
    token_request = requests[-1]
    form = parse_qs(token_request.content.decode())
    assert form["resource"] == [RESOURCE]
    assert form["client_secret"] == [CLIENT["client_secret"]]
    from base64 import urlsafe_b64encode

    challenge = urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
    assert params["code_challenge"] == [challenge.decode().rstrip("=")]
    assert client.get("/api/status").json()["data"]["auth"] == "configured"
    response = bridge(client, broker, [[TOOLS["orders"], {"page": 1}]])
    assert response.json()["ok"]
    assert calls[-1][1] == {"Authorization": "Bearer SYNTHETIC-ACCESS"}
    database = (broker.settings.vault_directory / "vault.sqlite3").read_bytes()
    visible = response.text + client.get("/api/status").text + caplog.text
    for secret in ("SYNTHETIC-SECRET", "SYNTHETIC-ACCESS", "SYNTHETIC-REFRESH", "CODE"):
        assert secret.encode() not in database
        assert secret not in visible


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": 456},
        {"age": 121},
        {"age": -60},
        {"chat_type": "group"},
        {"user": '{"id":"123"}'},
    ],
)
def test_reject_wrong_identity_or_stale_telegram(setup, changes):
    broker, client, requests, _ = setup
    response = client.post("/api/session", json={"init_data": signed(broker.settings, **changes)})
    assert response.status_code == 401
    assert not requests


def test_telegram_signature_duplicate_and_replay(setup):
    broker, client, _, _ = setup
    raw = signed(broker.settings)
    for invalid in (raw + "&auth_date=1", raw.replace("123", "456"), raw + "&extra=1"):
        assert client.post("/api/session", json={"init_data": invalid}).status_code == 401
    assert client.post("/api/session", json={"init_data": raw}).status_code == 200
    reordered = "&".join(reversed(raw.split("&")))
    assert client.post("/api/session", json={"init_data": reordered}).status_code == 401


def test_cross_bot_signature_rejected(setup):
    broker, _, _, _ = setup
    with pytest.raises(VVError):
        verify_telegram(signed(broker.settings), "another-token", broker.settings.owner_id)


def test_bot_token_alone_cannot_forge_browser_login(setup):
    broker, client, _, _ = setup
    values = {key: items[0] for key, items in parse_qs(signed(broker.settings)).items()}
    values["signature"] = urlsafe_b64encode(b"x" * 64).decode().rstrip("=")
    del values["hash"]
    message = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    key = hmac.digest(b"WebAppData", broker.settings.bot_token.encode(), "sha256")
    values["hash"] = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    assert client.post("/api/session", json={"init_data": urlencode(values)}).status_code == 401


@pytest.mark.parametrize("path", ["/api/session", "/api/connect", "/api/disconnect"])
def test_csrf_rejected_before_processing(setup, path):
    _, client, requests, _ = setup
    assert client.post(path, json={}, headers={"origin": "https://evil.example"}).status_code == 401
    assert not requests


def test_no_secret_form_before_auth_and_no_external_scripts_after(setup):
    broker, client, _, _ = setup
    assert client.get("/connect").status_code == 401
    authenticate(broker, client)
    response = client.get("/connect")
    assert response.status_code == 200
    assert "telegram.org" not in response.text
    assert "script-src 'self';" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    javascript = client.get("/assets/connect.js").text
    for forbidden in ("localStorage", "sendData", "innerHTML", "console.log"):
        assert forbidden not in javascript


def test_callback_binding_replay_and_duplicate_parameters(setup):
    broker, client, requests, _ = setup
    params = begin(broker, client)
    state = params["state"][0]
    rejected_callback(client.get("/oauth/callback", params={"state": "wrong", "code": "CODE"}))
    rejected_callback(
        client.get(
            "/oauth/callback?" + urlencode([("state", state), ("state", state), ("code", "CODE")])
        )
    )
    cookie = client.cookies.get(COOKIE)
    client.cookies.clear()
    rejected_callback(client.get("/oauth/callback", params={"state": state, "code": "CODE"}))
    client.cookies.set(COOKIE, cookie)
    assert (
        client.get(
            "/oauth/callback", params={"state": state, "code": "CODE"}, follow_redirects=False
        ).status_code
        == 303
    )
    count = len(requests)
    rejected_callback(client.get("/oauth/callback", params={"state": state, "code": "CODE"}))
    assert len(requests) == count


def test_denial_preserves_existing_account(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    original = broker.bridge_status()
    params = begin(broker, client)
    response = client.get(
        "/oauth/callback", params={"state": params["state"][0], "error": "denied"}
    )
    rejected_callback(response)
    assert broker.bridge_status() == original


def test_exchange_failure_consumes_attempt_preserves_existing(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    original = broker.bridge_status()
    params = begin(broker, client)
    broker.http_factory = lambda: httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="SYNTHETIC-SECRET"))
    )
    callback = {"state": params["state"][0], "code": "CODE"}
    response = client.get("/oauth/callback", params=callback)
    rejected_callback(response)
    assert "SYNTHETIC-SECRET" not in response.text
    rejected_callback(client.get("/oauth/callback", params=callback))
    assert broker.bridge_status() == original


def test_disconnect_invalidates_pending_and_account(setup):
    broker, client, _, calls = setup
    connect(broker, client)
    context = broker.bridge_status()["context"]
    params = begin(broker, client)
    assert client.post("/api/disconnect", json={}).json()["ok"]
    rejected_callback(
        client.get("/oauth/callback", params={"state": params["state"][0], "code": "CODE"})
    )
    assert (
        bridge(client, broker, [[TOOLS["orders"], {"page": 1}]], context=context).json()["error"][
            "code"
        ]
        == "REVIEW_REQUIRED"
    )
    assert (
        bridge(client, broker, [[TOOLS["orders"], {"page": 1}]]).json()["error"]["code"]
        == "AUTH_REQUIRED"
    )
    assert not calls


@pytest.mark.parametrize(
    "values",
    [
        {"redirect_uri": "https://evil.example/oauth/callback"},
        {"endpoint": "https://evil.example"},
        {"client_secret": ""},
        {"token_endpoint_auth_method": "bad"},
        {"scope": ["bad"]},
    ],
)
def test_reject_untrusted_config_without_echoing_secrets(setup, values):
    broker, client, requests, _ = setup
    authenticate(broker, client)
    response = client.post("/api/connect", json={**CLIENT, **values})
    assert response.status_code == 400
    assert CLIENT["client_secret"] not in response.text
    assert not requests


def test_body_limits_and_no_form_encoded_secrets(setup):
    _, client, _, _ = setup
    assert client.post("/api/session", json={"init_data": "x" * 32769}).status_code == 400
    assert client.post("/api/connect", data=CLIENT).status_code == 400


def test_instance_credential_cannot_access_other_broker(setup, tmp_path):
    broker, client, _, _ = setup
    other = Settings(
        **{
            **broker.settings.model_dump(),
            "bridge_key": "different" * 8,
            "vault_directory": tmp_path / "other",
        }
    )
    second = Broker(other)
    with pytest.raises(VVError):
        second.bridge_auth("Bearer " + broker.settings.bridge_key)
    response = client.get("/bridge/status", headers={"authorization": "Bearer " + other.bridge_key})
    assert response.status_code == 401
    assert other.bridge_key not in response.text


@pytest.mark.parametrize(
    "calls,confirmed,code",
    [
        ([["arbitrary-tool", {}]], False, "INVALID_INPUT"),
        ([[TOOLS["orders"], {"page": 1, "user_id": 456}]], False, "INVALID_INPUT"),
        ([[TOOLS["personal"], {}]], False, "REVIEW_REQUIRED"),
        ([[TOOLS["personal"], {}], [TOOLS["favorite"], {}]], True, "REVIEW_REQUIRED"),
        (
            [[TOOLS["link"], {"products": [{"id": index + 1, "q": 1} for index in range(21)]}]],
            True,
            "INVALID_INPUT",
        ),
        ([[TOOLS["link"], {"products": [{"id": 1, "q": 41}]}]], True, "INVALID_INPUT"),
    ],
)
def test_bridge_schema_and_mutation_guards(setup, calls, confirmed, code):
    broker, client, _, dispatched = setup
    response = bridge(client, broker, calls, confirmed=confirmed)
    assert response.json()["error"]["code"] == code
    assert not dispatched


def test_refresh_serialized_and_preserves_context(setup):
    broker, client, requests, calls = setup
    connect(broker, client)
    context = broker.bridge_status()["context"]
    with broker.vault.transaction() as connection:
        account = broker.vault.get(connection, "account")
        account["expires_at"] = 0
        broker.vault.put(connection, "account", account)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: broker.call([[TOOLS["favorite"], {}]], context), range(2))
        )
    assert len(results) == 2
    refreshes = [request for request in requests if b"grant_type=refresh_token" in request.content]
    assert len(refreshes) == 1
    assert broker.bridge_status()["context"] == context
    assert len(calls) == 2


def test_broker_survives_restart_encrypted_store(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    assert Broker(broker.settings).bridge_status() == broker.bridge_status()


def configure_cli(monkeypatch, tmp_path, broker):
    key_file = tmp_path / "instance.json"
    key_file.write_text(json.dumps({"bridge_key": broker.settings.bridge_key}))
    key_file.chmod(0o600)
    monkeypatch.setenv("VV_BROKER_URL", "https://connect.example")
    monkeypatch.setenv("VV_BROKER_KEY_FILE", str(key_file))
    monkeypatch.setenv("VV_STATE_DIR", str(tmp_path / "baskets"))
    monkeypatch.delenv("VV_MCP_TEST_URL", raising=False)


def test_cli_uses_bridge_without_accessing_oauth_files(setup, monkeypatch, tmp_path):
    broker, client, _, calls = setup
    connect(broker, client)
    configure_cli(monkeypatch, tmp_path, broker)

    def forbidden(*args, **kwargs):
        raise AssertionError("Agent must not read local OAuth files")

    monkeypatch.setattr(AuthStore, "read", forbidden)
    monkeypatch.setattr(AuthStore, "status", forbidden)

    def route(request):
        response = client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(response.status_code, content=response.content)

    original = httpx.Client
    monkeypatch.setattr(
        "vv.bridge.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(route), **kwargs),
    )
    runner = CliRunner()
    for arguments in (["doctor"], ["auth", "status"], ["auth", "connect"], ["orders", "list"]):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, result.output
        assert "SYNTHETIC-ACCESS" not in result.output
    for arguments in (["auth", "logout"], ["auth", "login", "--client-file", "unused"]):
        result = runner.invoke(app, arguments)
        assert json.loads(result.output)["error"]["code"] == "REVIEW_REQUIRED"
    assert calls[-1][0] == [[TOOLS["orders"], {"page": 1}]]


def test_bridge_transport_mutation_not_retried(setup, monkeypatch, tmp_path):
    broker, _, _, _ = setup
    configure_cli(monkeypatch, tmp_path, broker)
    provider = BrokerProvider()
    provider._context = "public"
    count = []

    def fail(request):
        count.append(request)
        raise httpx.ReadTimeout("SECRET")

    original = httpx.Client
    monkeypatch.setattr(
        "vv.bridge.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(fail), **kwargs),
    )
    with pytest.raises(VVError) as caught:
        provider.batch([(TOOLS["link"], {"products": [{"id": 1, "q": 1}]})])
    assert caught.value.code == Code.OUTCOME_UNKNOWN
    assert "SECRET" not in str(caught.value)
    assert len(count) == 1


def test_refresh_denied_never_falls_back_to_public(setup):
    broker, client, _, calls = setup
    connect(broker, client)
    with broker.vault.transaction() as connection:
        account = broker.vault.get(connection, "account")
        account["expires_at"] = 0
        broker.vault.put(connection, "account", account, ttl=None)
    broker.http_factory = lambda: httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": "invalid_grant"})
        )
    )
    for _ in range(2):
        response = bridge(client, broker, [[TOOLS["search"], {"q": "milk"}]])
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert not calls
    assert broker.bridge_status()["context"] == account["context"]


def test_expired_attempt_rejected(setup):
    broker, client, _, _ = setup
    params = begin(broker, client)
    with broker.vault.transaction() as connection:
        connection.execute("UPDATE records SET expires=0 WHERE name='attempt'")
    response = client.get("/oauth/callback", params={"state": params["state"][0], "code": "CODE"})
    rejected_callback(response)
    assert broker.bridge_status()["auth"] == "not_configured"


def test_callback_cannot_move_to_another_authenticated_browser(setup):
    broker, client, requests, _ = setup
    params = begin(broker, client)
    authenticate(broker, client)
    response = client.get("/oauth/callback", params={"state": params["state"][0], "code": "CODE"})
    rejected_callback(response)
    assert all(request.url.path != "/oauth2/token" for request in requests)


def test_parallel_callback_is_single_use(setup):
    broker, client, requests, _ = setup
    params = begin(broker, client)
    session = client.cookies.get(COOKIE)

    def finish(_):
        try:
            broker.callback(session, [("state", params["state"][0]), ("code", "CODE")])
            return "ok"
        except VVError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(finish, range(2))) == ["ok", "rejected"]
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 1


def test_vault_key_mismatch_never_reads_old_account(setup):
    broker, client, _, _ = setup
    connect(broker, client)
    settings = Settings(
        **{**broker.settings.model_dump(), "encryption_key": Fernet.generate_key().decode()}
    )
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        Broker(settings)


@pytest.mark.parametrize("changes", [{"owner_id": 456}, {"bot_token": "456:" + "different" * 5}])
def test_vault_cannot_be_reassigned_to_another_owner(setup, changes):
    broker, _, _, _ = setup
    settings = Settings(**{**broker.settings.model_dump(), **changes})
    with pytest.raises(ValueError, match="different owner"):
        Broker(settings)


@pytest.mark.parametrize(
    "result_status,expected", [(200, None), (401, "AUTH_REQUIRED"), (503, "OUTCOME_UNKNOWN")]
)
def test_broker_real_sdk_transport(setup, monkeypatch, result_status, expected):
    broker, client, _, _ = setup
    connect(broker, client)
    broker.dispatch = broker.dispatch_mcp
    requests = []
    tool = TOOLS["personal"]

    def transport(request):
        assert str(request.url) == RESOURCE
        assert request.headers["authorization"] == "Bearer SYNTHETIC-ACCESS"
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        method = body["method"]
        if method == "initialize":
            result = {
                "protocolVersion": body["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": tool, "inputSchema": broker.schemas[tool]}]}
        else:
            assert method == "tools/call"
            requests.append(body)
            if result_status != 200:
                return httpx.Response(result_status, text="SYNTHETIC-SECRET")
            result = {
                "content": [
                    {"type": "text", "text": json.dumps({"ok": True, "data": {"synthetic": True}})}
                ]
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs),
    )
    response = bridge(client, broker, [[tool, {}]], confirmed=True)
    if expected:
        assert response.json()["error"]["code"] == expected
    else:
        assert response.json()["data"] == [{"synthetic": True}]
    assert len(requests) == 1
    assert "SYNTHETIC-SECRET" not in response.text


@pytest.mark.parametrize("connected", [False, True])
def test_cli_basket_lifecycle_through_bridge_and_loopback_mcp(
    setup, monkeypatch, tmp_path, connected
):
    import asyncio

    from e2e.support import fixture_server
    from vv.mcp_provider import MCPProvider

    broker, client, _, _ = setup
    if connected:
        connect(broker, client)
    configure_cli(monkeypatch, tmp_path, broker)
    original = httpx.Client

    def route(request):
        response = client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(response.status_code, content=response.content)

    with fixture_server(tmp_path / "fixture") as fixture:

        def dispatch(batch, headers):
            provider = MCPProvider.__new__(MCPProvider)
            provider.endpoint = fixture["env"]["VV_MCP_TEST_URL"]
            provider.headers = headers
            provider.schemas = broker.schemas
            return asyncio.run(provider._batch(batch))

        broker.dispatch = dispatch
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(transport=httpx.MockTransport(route), **kwargs),
        )
        request_file = tmp_path / "request.json"
        request_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "items": [{"product_id": 101, "quantity": "2", "unit": "package"}],
                    "constraints": {"max_goods_total": "300"},
                }
            )
        )
        runner = CliRunner()

        def invoke(*args):
            result = runner.invoke(app, list(args))
            assert result.exit_code == 0, result.output
            return json.loads(result.output)["data"]

        invoke("basket", "import", "web", "--file", str(request_file))
        checked = invoke("basket", "check", "web", "--refresh")
        assert checked["report"]["scope"] == ("authenticated_live" if connected else "public_live")
        assert checked["report"]["goods_total"] == "200.00"
        linked = invoke("basket", "link", "web", "--checked-hash", checked["check_hash"])
        assert linked["state"] == "link_created"
        assert (
            invoke("basket", "link", "web", "--checked-hash", checked["check_hash"])["link"]
            == linked["link"]
        )
        events = [json.loads(line) for line in fixture["journal"].read_text().splitlines()]
        assert sum(event["name"] == TOOLS["link"] for event in events) == 1

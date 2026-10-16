import hashlib
import json
import threading
import time
from base64 import urlsafe_b64encode
from http.server import HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from vv import auth
from vv.cli import app
from vv.errors import Code, VVError
from vv.mcp_provider import MCPProvider
from vv.store import checked_hash

PROVIDER_BATCH = MCPProvider.batch


@pytest.fixture
def auth_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VV_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("VV_PROFILE", "default")
    return auth.AuthStore()


def config(**changes):
    return auth.ClientConfig.model_validate(
        {
            "client_id": "client",
            "client_secret": "SECRET",
            "token_endpoint_auth_method": "client_secret_post",
            "redirect_uri": "http://127.0.0.1:18765/callback",
            "scope": "openid offline_access",
            **changes,
        }
    )


def seed(store, expires=None, **changes):
    session = {
        "config": config().model_dump(),
        "context": "session-one",
        "expires_at": time.time() + 600 if expires is None else expires,
        "token": {"access_token": "ACCESS", "refresh_token": "REFRESH", "token_type": "Bearer"},
        **changes,
    }
    with store.locked():
        store.write(session)
    return session


def transport_factory(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def metadata():
    return {
        "issuer": auth.ISSUER,
        "authorization_endpoint": auth.ISSUER + "oauth2/auth",
        "token_endpoint": auth.ISSUER + "oauth2/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }


def discovery_response(request, changes=None):
    if "oauth-protected-resource" in request.url.path:
        return httpx.Response(
            200,
            json={
                "resource": auth.RESOURCE,
                "authorization_servers": [auth.ISSUER],
            },
        )
    return httpx.Response(200, json={**metadata(), **(changes or {})})


def test_discovery_contract():
    with httpx.Client(transport=httpx.MockTransport(discovery_response)) as client:
        assert str(auth.discover(client).issuer) == auth.ISSUER


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": "https://evil.example/"},
        {"token_endpoint": "https://evil.example/token"},
        {"code_challenge_methods_supported": ["plain"]},
        {"grant_types_supported": []},
    ],
)
def test_discovery_fails_closed(changes):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: discovery_response(request, changes))
    ) as client:
        with pytest.raises(VVError, match="trusted contract"):
            auth.discover(client)


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example/callback",
        "http://0.0.0.0:8000/callback",
        "http://localhost:8000/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:8000/callback?code=x",
        "http://user@127.0.0.1:8000/callback",
    ],
)
def test_redirect_must_be_explicit_loopback(uri):
    with pytest.raises(ValidationError):
        config(redirect_uri=uri)


def test_private_storage_status_and_logout(auth_home, monkeypatch):
    seed(auth_home)
    assert auth_home.path.stat().st_mode & 0o777 == 0o600
    assert auth_home.directory.stat().st_mode & 0o777 == 0o700
    output = CliRunner().invoke(app, ["auth", "status", "--json"])
    assert output.exit_code == 0
    assert "ACCESS" not in output.stdout and "SECRET" not in output.stdout
    monkeypatch.setenv("VV_PROFILE", "another")
    assert auth.AuthStore().status() == {"auth": "not_configured"}
    assert auth_home.logout()["remote_revoked"] is False
    assert not auth_home.path.exists()


def test_unsafe_secret_permissions_and_symlinks(auth_home, tmp_path):
    seed(auth_home)
    auth_home.path.chmod(0o644)
    with pytest.raises(VVError):
        auth_home.read()
    auth_home.path.unlink()
    auth_home.path.symlink_to(tmp_path / "other")
    with pytest.raises(OSError):
        auth_home.read()


def test_public_credentials(auth_home):
    with auth.credentials(auth.RESOURCE) as result:
        assert result == ({}, "public")


def test_credentials_never_sent_to_other_host(auth_home):
    seed(auth_home)
    with pytest.raises(VVError):
        with auth.credentials("http://127.0.0.1:8000/mcp"):
            pytest.fail("Credentials leaked")


def test_refresh_rotates_and_persists_absolute_expiry(auth_home, monkeypatch):
    seed(auth_home, expires=1)
    requests = []

    def handler(request):
        requests.append(request)
        values = parse_qs(request.content.decode())
        assert values["refresh_token"] == ["REFRESH"]
        assert values["client_secret"] == ["SECRET"]
        assert values["resource"] == [auth.RESOURCE]
        return httpx.Response(
            200,
            json={
                "access_token": "NEW",
                "refresh_token": "ROTATED",
                "token_type": "Bearer",
                "expires_in": 600,
            },
        )

    transport_factory(monkeypatch, handler)
    for _ in range(2):
        with auth.credentials(auth.RESOURCE) as (headers, context):
            assert headers == {"Authorization": "Bearer NEW"}
            assert context == "session-one"
    assert len(requests) == 1
    assert auth.AuthStore().read()["expires_at"] > time.time() + 500
    assert auth_home.read()["token"]["refresh_token"] == "ROTATED"


@pytest.mark.parametrize(
    "status, code",
    [
        (400, Code.AUTH_REQUIRED),
        (401, Code.AUTH_REQUIRED),
        (503, Code.NETWORK_ERROR),
        (302, Code.NETWORK_ERROR),
    ],
)
def test_failed_refresh_no_public_fallback(auth_home, monkeypatch, status, code):
    original = seed(auth_home, expires=1)
    transport_factory(monkeypatch, lambda request: httpx.Response(status, json={"error": "SECRET"}))
    with pytest.raises(VVError) as raised:
        with auth.credentials(auth.RESOURCE):
            pytest.fail("Failed refresh was accepted")
    assert raised.value.code == code
    assert "SECRET" not in str(raised.value)
    assert auth_home.read() == original


def test_expired_without_refresh_requires_login(auth_home):
    seed(auth_home, expires=1, token={"access_token": "ACCESS"})
    with pytest.raises(VVError, match="expired"):
        with auth.credentials(auth.RESOURCE):
            pytest.fail("Expired token accepted")


@pytest.mark.parametrize(
    "values, succeeds",
    [
        ({"state": "expected", "code": "CODE"}, True),
        ({"state": "wrong", "code": "CODE"}, False),
        ({"state": "expected", "error": "access_denied"}, False),
        ({"state": ["expected", "expected"], "code": "CODE"}, False),
        ({"state": "expected", "code": ["A", "B"]}, False),
        ({"state": "ю", "code": "CODE"}, False),
    ],
)
def test_real_loopback_callback(values, succeeds):
    with HTTPServer(("127.0.0.1", 0), auth.Callback) as server:
        url = f"http://127.0.0.1:{server.server_port}/callback"
        worker = threading.Thread(
            target=lambda: httpx.get(url + "?" + urlencode(values, doseq=True))
        )
        worker.start()
        try:
            if succeeds:
                assert auth.receive_callback(server, url, "expected", 3) == "CODE"
            else:
                with pytest.raises(VVError):
                    auth.receive_callback(server, url, "expected", 3)
        finally:
            worker.join(timeout=5)


def test_callback_timeout():
    with HTTPServer(("127.0.0.1", 0), auth.Callback) as server:
        with pytest.raises(VVError, match="timed out"):
            auth.receive_callback(server, "http://127.0.0.1:8000/callback", "state", 0)


def test_login_pkce_no_secret_in_url(auth_home, tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(config().model_dump_json())
    path.chmod(0o600)
    captured = {}

    def handler(request):
        if request.method == "GET":
            return discovery_response(request)
        values = parse_qs(request.content.decode())
        verifier = values["code_verifier"][0]
        challenge = (
            urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        )
        assert challenge == captured["code_challenge"][0]
        return httpx.Response(
            200, json={"access_token": "ACCESS", "token_type": "Bearer", "expires_in": 600}
        )

    def announce(url):
        assert "SECRET" not in url
        captured.update(parse_qs(urlsplit(url).query))

    monkeypatch.setattr(auth, "receive_callback", lambda server, uri, state, timeout: "CODE")
    transport_factory(monkeypatch, handler)
    auth.login(path, announce)
    assert captured["code_challenge_method"] == ["S256"]
    assert len(captured["state"][0]) >= 32
    assert auth_home.status()["auth"] == "configured"


def test_login_requires_private_terminal(auth_home):
    result = CliRunner().invoke(app, ["auth", "login", "--client-file", "missing.json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "AUTH_REQUIRED"


def test_context_changes_invalidate_existing_check(auth_home, service, shopping_request):
    service.import_request("basket", shopping_request)
    basket = service.check("basket")
    original = checked_hash("default", basket)
    basket.auth_context = "another-session"
    assert checked_hash("default", basket) != original
    with pytest.raises(VVError) as raised:
        service.validate_check(basket, original)
    assert raised.value.code == Code.REVIEW_REQUIRED


def test_provider_captures_context(auth_home):
    assert MCPProvider().auth_context == "public"
    seed(auth_home)
    assert MCPProvider().auth_context == "session-one"


def test_lock_serializes_sessions(auth_home):
    entered = threading.Event()

    def worker():
        with auth.AuthStore().locked():
            entered.set()

    with auth_home.locked():
        thread = threading.Thread(target=worker)
        thread.start()
        assert not entered.wait(0.1)
    thread.join(timeout=2)
    assert entered.is_set()


@pytest.mark.parametrize("status_code", [200, 401, 503])
def test_authenticated_mcp_sdk_transport(auth_home, monkeypatch, status_code):
    seed(auth_home)
    provider = MCPProvider()
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer ACCESS"
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        if "id" not in body:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": body["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "vkusvill_product_lp",
                        "inputSchema": provider.schemas["vkusvill_product_lp"],
                    }
                ]
            }
        else:
            assert method == "tools/call"
            if status_code != 200:
                return httpx.Response(status_code, text="SECRET provider details")
            result = {
                "content": [
                    {"type": "text", "text": json.dumps({"ok": True, "data": {"test": True}})}
                ]
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    if status_code == 200:
        assert PROVIDER_BATCH(provider, [("vkusvill_product_lp", {})]) == [{"test": True}]
    else:
        with pytest.raises(VVError) as raised:
            PROVIDER_BATCH(provider, [("vkusvill_product_lp", {})])
        assert raised.value.code == (
            Code.AUTH_REQUIRED if status_code == 401 else Code.PROVIDER_ERROR
        )
        assert "SECRET" not in str(raised.value)
    calls = [
        request
        for request in requests
        if request.method == "POST" and json.loads(request.content)["method"] == "tools/call"
    ]
    assert len(calls) == 1
    assert requests
    assert provider.headers == {}


def test_changed_session_blocks_mcp_before_network(auth_home):
    provider = MCPProvider()
    seed(auth_home)
    with pytest.raises(VVError) as raised:
        PROVIDER_BATCH(provider, [("vkusvill_product_lp", {})])
    assert raised.value.code == Code.REVIEW_REQUIRED


@pytest.mark.parametrize("method", ["none", "client_secret_basic", "client_secret_post"])
def test_registered_authentication_methods(method):
    def handle(request):
        body = parse_qs(request.content.decode())
        if method == "client_secret_basic":
            assert request.headers["Authorization"].startswith("Basic ")
            assert "client_secret" not in body
        elif method == "client_secret_post":
            assert body["client_secret"] == ["SECRET"]
            assert "Authorization" not in request.headers
        else:
            assert "client_secret" not in body and "Authorization" not in request.headers
        return httpx.Response(
            200, json={"access_token": "ACCESS", "token_type": "Bearer", "expires_in": 600}
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        token = auth.exchange(
            client,
            config(token_endpoint_auth_method=method),
            {"grant_type": "refresh_token"},
            "OLD",
        )
        assert token.refresh_token == "OLD"


def test_failed_login_preserves_existing_session(auth_home, tmp_path, monkeypatch):
    previous = seed(auth_home)
    path = tmp_path / "client.json"
    path.write_text(config().model_dump_json())
    path.chmod(0o600)
    transport_factory(monkeypatch, discovery_response)

    def denied(*args):
        raise VVError(Code.AUTH_REQUIRED, "OAuth consent denied.")

    monkeypatch.setattr(auth, "receive_callback", denied)
    with pytest.raises(VVError):
        auth.login(path, lambda url: None)
    assert auth_home.read() == previous


@pytest.mark.parametrize(
    "token",
    [
        {"access_token": "", "expires_in": 600},
        {"access_token": "ACCESS", "expires_in": 0},
        {"access_token": "ACCESS", "expires_in": -10},
        {"access_token": "ACCESS"},
    ],
)
def test_invalid_token_is_not_accepted(token):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"token_type": "Bearer", **token})
        )
    ) as client:
        with pytest.raises(VVError) as raised:
            auth.exchange(client, config(), {})
    assert raised.value.code == Code.SCHEMA_CHANGED

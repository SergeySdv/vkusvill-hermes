import ipaddress
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from test_broker import CLIENT, signed
from test_broker import setup as setup

from vv.broker.server import create_app

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def browser(setup, tmp_path):
    broker, _, requests, _ = setup
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"https://127.0.0.1:{listener.getsockname()[1]}"
    broker.settings.public_origin = origin
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-loopback")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    private_key = tmp_path / "test.key"
    private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_key.chmod(0o600)
    cert_file = tmp_path / "test.crt"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(broker),
            ssl_keyfile=str(private_key),
            ssl_certfile=str(cert_file),
            access_log=False,
            log_level="critical",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    try:
        with playwright.sync_playwright() as driver:
            instance = driver.chromium.launch()
            context = instance.new_context(ignore_https_errors=True)
            visited = []

            def route(request_route):
                target = urlsplit(request_route.request.url)
                visited.append(target.netloc + target.path)
                if target.netloc == "telegram.org" and target.path == "/js/telegram-web-app.js":
                    request_route.fulfill(
                        content_type="text/javascript",
                        body="window.Telegram={WebApp:{ready(){},initData:"
                        + json.dumps(signed(broker.settings))
                        + "}};",
                    )
                elif target.netloc == "oauth.vkusvill.ru" and target.path == "/oauth2/auth":
                    values = parse_qs(target.query)
                    callback = (
                        values["redirect_uri"][0]
                        + "?"
                        + urlencode({"state": values["state"][0], "code": "BROWSER-CANARY-CODE"})
                    )
                    request_route.fulfill(
                        content_type="text/html",
                        body='<a href="'
                        + callback.replace("&", "&amp;")
                        + '">Allow synthetic consent</a>',
                    )
                elif target.netloc == urlsplit(origin).netloc:
                    request_route.continue_()
                else:
                    request_route.abort()
                    raise AssertionError("Unexpected external browser request")

            context.route("**/*", route)
            try:
                yield context, visited, requests, origin
            finally:
                context.close()
                instance.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


def login(page, origin):
    page.goto(origin + "/")
    page.wait_for_url(origin + "/connect")
    page.get_by_label("Client ID из письма").fill(CLIENT["client_id"])
    page.get_by_label("Client secret (если выдан)").fill(CLIENT["client_secret"])
    assert page.locator("select").count() == 0
    assert page.locator('[name="token_endpoint_auth_method"]').input_value() == "client_secret_post"
    page.get_by_label("Scope — выданные права").fill(CLIENT["scope"])
    page.get_by_role("button", name="Подключить через ВкусВилл").click()
    page.wait_for_url("https://oauth.vkusvill.ru/oauth2/auth?*")


def test_browser_reconnect_without_client_fields(browser):
    context, visited, requests, origin = browser
    page = context.new_page()
    login(page, origin)
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/connect")
    page.get_by_role("button", name="Войти снова без ввода ключей").click()
    page.wait_for_url("https://oauth.vkusvill.ru/oauth2/auth?*")
    params = parse_qs(urlsplit(page.url).query)
    assert params["scope"][0].split().count("offline_access") == 1
    assert params["prompt"] == ["consent"]
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/connect")
    playwright.expect(page.locator("#connect")).to_be_hidden()
    assert "SYNTHETIC-SECRET" not in page.content()
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 2


def test_browser_consent_callback_no_secrets_in_storage(browser):
    context, visited, requests, origin = browser
    page = context.new_page()
    login(page, origin)
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/connect")
    playwright.expect(page.locator("#message")).to_contain_text("Подключение сохранено")
    playwright.expect(page.locator("#connect")).to_be_hidden()
    playwright.expect(page.locator("#setup-help")).to_be_hidden()
    assert page.get_by_label("Client secret (если выдан)").input_value() == ""
    assert (
        page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
    )
    assert "BROWSER-CANARY-CODE" not in page.content()
    assert "SYNTHETIC-SECRET" not in page.content()
    cookies = context.cookies()
    assert len(cookies) == 1
    assert cookies[0]["httpOnly"] and cookies[0]["secure"] and cookies[0]["sameSite"] == "Lax"
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 1
    assert not any("api.telegram.org" in url for url in visited)
    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Отключить", exact=True).click()
    playwright.expect(page.locator("#message")).to_contain_text("не подключён")


def test_browser_missing_cookie_cleans_callback_without_exchange(browser):
    context, _, requests, origin = browser
    page = context.new_page()
    login(page, origin)
    context.clear_cookies()
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/oauth/problem")
    playwright.expect(page.get_by_role("heading")).to_have_text("Вход не завершён")
    assert "BROWSER-CANARY-CODE" not in page.content()
    assert all(request.url.path != "/oauth2/token" for request in requests)


def test_browser_expired_submit_visible_error_and_secret_cleared(browser):
    context, _, requests, origin = browser
    page = context.new_page()
    page.goto(origin + "/")
    page.wait_for_url(origin + "/connect")
    page.get_by_label("Client ID из письма").fill(CLIENT["client_id"])
    page.get_by_label("Client secret (если выдан)").fill(CLIENT["client_secret"])
    page.get_by_label("Scope — выданные права").fill(CLIENT["scope"])
    context.clear_cookies()
    page.get_by_role("button", name="Подключить через ВкусВилл").click()
    playwright.expect(page.locator("#action-message")).to_contain_text("Сессия формы истекла")
    playwright.expect(page.locator("#action-message")).to_be_in_viewport()
    assert page.get_by_label("Client secret (если выдан)").input_value() == ""
    assert not requests
    page.reload()
    playwright.expect(page.get_by_role("heading")).to_have_text("Сессия формы истекла")


def test_connected_reopen_does_not_repeat_token_exchange(browser):
    context, _, requests, origin = browser
    page = context.new_page()
    login(page, origin)
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/connect")
    context.clear_cookies()
    page.goto(origin + "/")
    page.wait_for_url(origin + "/connect")
    playwright.expect(page.locator("#message")).to_contain_text("Подключение сохранено")
    playwright.expect(page.locator("#connect")).to_be_hidden()
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 1


def test_disconnect_cancel_preserves_connection(browser):
    context, _, requests, origin = browser
    page = context.new_page()
    login(page, origin)
    page.get_by_role("link", name="Allow synthetic consent").click()
    page.wait_for_url(origin + "/connect")
    playwright.expect(page.locator("#message")).to_contain_text("Подключение сохранено")
    page.on("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Отключить", exact=True).click()
    page.reload()
    playwright.expect(page.locator("#message")).to_contain_text("Подключение сохранено")
    assert sum(request.url.path == "/oauth2/token" for request in requests) == 1

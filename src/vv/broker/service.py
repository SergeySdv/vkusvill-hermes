import asyncio
import hmac
import json
import secrets
import time
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from jsonschema import Draft202012Validator
from mcp.client.auth.oauth2 import PKCEParameters
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vv.auth import ISSUER, RESOURCE, discover, exchange
from vv.broker.security import WebClient, digest, verify_telegram
from vv.broker.storage import Vault
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider
from vv.models import CartPayload


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_origin: str
    owner_id: int = Field(gt=0, strict=True)
    bot_token: str = Field(min_length=20, repr=False)
    bridge_key: str = Field(min_length=43, repr=False)
    encryption_key: str = Field(repr=False)
    vault_directory: Path

    @model_validator(mode="after")
    def validate_origin(self):
        bot_id, separator, secret = self.bot_token.partition(":")
        if not separator or not bot_id.isascii() or not bot_id.isdigit() or not secret:
            raise ValueError("Invalid bot token format.")
        target = urlsplit(self.public_origin)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
            or target.path
            or target.query
            or target.fragment
            or target.port not in (None, 443)
        ):
            raise ValueError("public_origin must be a bare HTTPS origin.")
        return self

    @property
    def callback(self):
        return self.public_origin + "/oauth/callback"


class Broker:
    def __init__(self, settings: Settings, *, http_factory=None, dispatch=None):
        self.settings = settings
        existing = (settings.vault_directory / "vault.sqlite3").exists()
        self.vault = Vault(settings.vault_directory, settings.encryption_key)
        identity = {"owner_id": settings.owner_id, "bot_id": settings.bot_token.split(":", 1)[0]}
        with self.vault.transaction() as connection:
            binding = self.vault.get(connection, "identity")
            if existing and binding is None:
                raise ValueError(
                    "Existing vault identity missing; restore instead of reinitializing."
                )
            if binding is not None and binding != identity:
                raise ValueError("Vault belongs to a different owner or bot.")
            self.vault.put(connection, "identity", identity, ttl=None)
            if not self.vault.get(connection, "public_context"):
                self.vault.put(
                    connection, "public_context", "public:" + secrets.token_hex(32), ttl=None
                )
        self.http_factory = http_factory or (
            lambda: httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
        )
        self.dispatch = dispatch or self.dispatch_mcp
        self.schemas = json.loads(files("vv").joinpath("schemas.json").read_text())

    def authenticate(self, raw):
        fingerprint = verify_telegram(raw, self.settings.bot_token, self.settings.owner_id)
        with self.vault.transaction() as connection:
            self.vault.prune(connection)
            name = "telegram:" + fingerprint
            if self.vault.get(connection, name):
                raise VVError(Code.AUTH_REQUIRED, "Reopen the Mini App; login already used.")
            session = secrets.token_urlsafe(32)
            self.vault.put(connection, name, True, ttl=180)
            self.vault.put(connection, "browser:" + digest(session), True)
            return session

    def browser(self, connection, session):
        if not session or not self.vault.get(connection, "browser:" + digest(session)):
            raise VVError(Code.AUTH_REQUIRED, "Reopen the Mini App to authenticate.")

    def browser_status(self, session):
        with self.vault.transaction() as connection:
            self.browser(connection, session)
            return {
                **self.status_record(
                    self.vault.get(connection, "account"),
                    self.vault.get(connection, "public_context"),
                ),
                "redirect_uri": self.settings.callback,
                "pending": self.vault.get(connection, "attempt") is not None,
            }

    @staticmethod
    def status_record(account, public_context):
        return {
            "auth": (
                "reconnect_required"
                if account and account.get("reconnect_required")
                else "configured"
                if account
                else "not_configured"
            ),
            "context": account["context"] if account else public_context,
            "expires_at": account["expires_at"] if account else None,
            "refresh_available": bool(account and account["token"].get("refresh_token")),
        }

    def begin(self, session, values):
        config = WebClient.model_validate({**values, "redirect_uri": self.settings.callback})
        with self.vault.transaction() as connection:
            self.browser(connection, session)
            previous = self.vault.get(connection, "attempt")
            if previous and previous["created"] > time.time() - 10:
                raise VVError(Code.REVIEW_REQUIRED, "Wait before starting another connection.")
            with self.http_factory() as client:
                metadata = discover(client)
            if config.token_endpoint_auth_method not in (
                metadata.token_endpoint_auth_methods_supported or []
            ):
                raise VVError(Code.SCHEMA_CHANGED, "Client method is not advertised.")
            pkce = PKCEParameters.generate()
            state = secrets.token_urlsafe(32)
            self.vault.put(
                connection,
                "attempt",
                {
                    "state": digest(state),
                    "session": digest(session),
                    "created": time.time(),
                    "verifier": pkce.code_verifier,
                    "config": config.model_dump(),
                },
                ttl=300,
            )
            return (
                ISSUER
                + "oauth2/auth?"
                + urlencode(
                    {
                        "response_type": "code",
                        "client_id": config.client_id,
                        "redirect_uri": config.redirect_uri,
                        "scope": config.scope,
                        "state": state,
                        "code_challenge": pkce.code_challenge,
                        "code_challenge_method": "S256",
                        "resource": RESOURCE,
                    }
                )
            )

    def callback(self, session, pairs):
        values = dict(pairs)
        if len(values) != len(pairs) or not values.get("state"):
            raise VVError(Code.AUTH_REQUIRED, "Invalid OAuth callback.")
        with self.vault.transaction() as connection:
            self.browser(connection, session)
            attempt = self.vault.get(connection, "attempt")
            if not attempt or not (
                hmac.compare_digest(attempt["state"], digest(values["state"]))
                and hmac.compare_digest(attempt["session"], digest(session))
            ):
                raise VVError(Code.AUTH_REQUIRED, "Expired or mismatched OAuth callback.")
            self.vault.delete(connection, "attempt")
            connection.commit()
            if "error" in values or not values.get("code"):
                raise VVError(Code.AUTH_REQUIRED, "Consent denied; previous connection unchanged.")
            config = WebClient.model_validate(attempt["config"])
            with self.http_factory() as client:
                token = exchange(
                    client,
                    config,
                    {
                        "grant_type": "authorization_code",
                        "code": values["code"],
                        "redirect_uri": config.redirect_uri,
                        "code_verifier": attempt["verifier"],
                    },
                )
            self.vault.put(
                connection,
                "account",
                {
                    "config": config.model_dump(),
                    "token": token.model_dump(),
                    "expires_at": time.time() + token.expires_in,
                    "context": secrets.token_hex(32),
                },
                ttl=None,
            )

    def disconnect(self, session):
        with self.vault.transaction() as connection:
            self.browser(connection, session)
            self.vault.delete(connection, "account")
            self.vault.delete(connection, "attempt")
            self.vault.put(
                connection, "public_context", "public:" + secrets.token_hex(32), ttl=None
            )
        return {"auth": "not_configured", "remote_revoked": False}

    def bridge_auth(self, credential):
        expected = "Bearer " + self.settings.bridge_key
        if not hmac.compare_digest(credential.encode(), expected.encode()):
            raise VVError(Code.AUTH_REQUIRED, "Invalid instance credential.")

    def bridge_status(self):
        with self.vault.transaction() as connection:
            return {
                **self.status_record(
                    self.vault.get(connection, "account"),
                    self.vault.get(connection, "public_context"),
                ),
                "onboarding_url": self.settings.public_origin,
            }

    def send_connect_button(self):
        with self.vault.transaction() as connection:
            previous = self.vault.get(connection, "connect_button")
            if previous == "sent":
                return {"button_sent": False, "recently_sent": True}
            if previous:
                raise VVError(Code.OUTCOME_UNKNOWN, "Check the chat; do not resend blindly.")
            self.vault.put(connection, "connect_button", "attempting", ttl=60)
        try:
            with self.http_factory() as client:
                response = client.post(
                    "https://api.telegram.org/bot" + self.settings.bot_token + "/sendMessage",
                    json={
                        "chat_id": self.settings.owner_id,
                        "text": (
                            "Мой ВкусВилл: подключение и управление доступом. "
                            "Ключи — только в форме."
                        ),
                        "reply_markup": {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "Мой ВкусВилл",
                                        "web_app": {"url": self.settings.public_origin},
                                    }
                                ]
                            ]
                        },
                    },
                )
                response.raise_for_status()
                value = response.json()
                if (
                    value.get("ok") is not True
                    or type(value.get("result", {}).get("message_id")) is not int
                ):
                    raise ValueError("Delivery unconfirmed")
        except Exception:
            raise VVError(
                Code.OUTCOME_UNKNOWN, "Button delivery unconfirmed; check the chat."
            ) from None
        with self.vault.transaction() as connection:
            self.vault.put(connection, "connect_button", "sent", ttl=60)
        return {"button_sent": True, "recently_sent": False}

    def call(self, calls, context, confirmed=False):
        if type(confirmed) is not bool or not isinstance(context, str):
            raise VVError(Code.INVALID_INPUT, "Invalid bridge context or confirmation.")
        if not isinstance(calls, list) or not 1 <= len(calls) <= 20:
            raise VVError(Code.INVALID_INPUT, "Expected 1–20 tool calls.")
        mutation = False
        for entry in calls:
            if not isinstance(entry, list) or len(entry) != 2:
                raise VVError(Code.INVALID_INPUT, "Invalid tool call.")
            name, arguments = entry
            if not isinstance(name, str) or name not in self.schemas:
                raise VVError(Code.INVALID_INPUT, "Tool not allowed.")
            schema = {**self.schemas[name], "additionalProperties": False}
            if not Draft202012Validator(schema).is_valid(arguments):
                raise VVError(Code.INVALID_INPUT, "Invalid tool arguments.")
            if name == TOOLS["link"]:
                payload = CartPayload.model_validate(arguments)
                if any(item.id is None for item in payload.products):
                    raise VVError(Code.REVIEW_REQUIRED, "Legacy cart identifiers rejected.")
            mutation |= name in (TOOLS["link"], TOOLS["personal"])
        if mutation and (confirmed is not True or len(calls) != 1):
            raise VVError(Code.REVIEW_REQUIRED, "Single explicitly confirmed mutation required.")
        with self.vault.transaction() as connection:
            account = self.vault.get(connection, "account")
            actual = account["context"] if account else self.vault.get(connection, "public_context")
            if context != actual:
                raise VVError(Code.REVIEW_REQUIRED, "Connection changed; refresh and review.")
            if not account and any(
                name in (TOOLS["orders"], TOOLS["favorite"], TOOLS["personal"]) for name, _ in calls
            ):
                raise VVError(Code.AUTH_REQUIRED, "Connect VkusVill in the Mini App first.")
            headers = {}
            if account:
                if account.get("reconnect_required"):
                    raise VVError(Code.AUTH_REQUIRED, "Reconnect in the Mini App.")
                if account["expires_at"] <= time.time() + 30:
                    refresh = account["token"].get("refresh_token")
                    if not refresh:
                        raise VVError(Code.AUTH_REQUIRED, "Reconnect in the Mini App.")
                    account["reconnect_required"] = True
                    self.vault.put(connection, "account", account, ttl=None)
                    connection.commit()
                    with self.http_factory() as client:
                        token = exchange(
                            client,
                            WebClient.model_validate(account["config"]),
                            {
                                "grant_type": "refresh_token",
                                "refresh_token": refresh,
                            },
                            refresh,
                        )
                    account.update(
                        token=token.model_dump(),
                        expires_at=time.time() + token.expires_in,
                        reconnect_required=False,
                    )
                    self.vault.put(connection, "account", account, ttl=None)
                    connection.commit()
                headers = {"Authorization": "Bearer " + account["token"]["access_token"]}
            result = self.dispatch(calls, headers)
            encoded = json.dumps(result, ensure_ascii=False)
            secrets_to_hide = [
                self.settings.bot_token,
                self.settings.bridge_key,
                self.settings.encryption_key,
            ]
            if account:
                secrets_to_hide.extend(
                    [
                        account["config"].get("client_secret"),
                        account["token"]["access_token"],
                        account["token"].get("refresh_token"),
                    ]
                )
            if len(encoded.encode()) > 2 * 1024 * 1024 or any(
                value and value in encoded for value in secrets_to_hide
            ):
                raise VVError(
                    Code.OUTCOME_UNKNOWN if mutation else Code.SCHEMA_CHANGED,
                    "Unsafe or oversized upstream response suppressed.",
                )
            return result

    def ready(self):
        with self.vault.transaction() as connection:
            identity = self.vault.get(connection, "identity")
            if not identity:
                raise ValueError("Vault identity missing.")
            self.vault.get(connection, "account")
        return {"ok": True}

    def dispatch_mcp(self, calls, headers):
        provider = MCPProvider.__new__(MCPProvider)
        provider.endpoint = RESOURCE
        provider.headers = headers
        provider.trust_env = False
        provider.schemas = self.schemas
        return asyncio.run(provider._batch(calls))

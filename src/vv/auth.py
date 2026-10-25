import fcntl
import hmac
import json
import os
import secrets
import stat
import tempfile
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote_plus, urlencode, urlsplit

import httpx
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.shared.auth import OAuthMetadata, OAuthToken, ProtectedResourceMetadata
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vv.errors import Code, VVError
from vv.store import validate_name

RESOURCE = "https://mcp.vkusvill.ru/mcp"
ISSUER = "https://oauth.vkusvill.ru/"


def is_public_context(value):
    return value == "public" or value.startswith("public:")


class ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1)
    client_secret: str | None = Field(default=None, repr=False)
    token_endpoint_auth_method: Literal["none", "client_secret_basic", "client_secret_post"]
    redirect_uri: str
    scope: str

    @model_validator(mode="after")
    def validate_client(self):
        target = urlsplit(self.redirect_uri)
        if (
            target.scheme != "http"
            or target.hostname != "127.0.0.1"
            or not target.port
            or target.username
            or target.password
            or target.query
            or target.fragment
            or not target.path.startswith("/")
        ):
            raise ValueError("Register an explicit loopback HTTP callback with a fixed port.")
        if self.token_endpoint_auth_method != "none" and not self.client_secret:
            raise ValueError("The registered method requires a client secret.")
        return self


def private_read(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise VVError(
                Code.STORAGE_ERROR, "OAuth files must be owner-only regular files (0600)."
            )
        return json.load(stream)


class AuthStore:
    def __init__(self):
        state = Path(os.environ.get("VV_STATE_DIR", str(Path.home() / ".local/state/vv")))
        self.directory = state / "auth" / validate_name(os.environ.get("VV_PROFILE", "default"))
        self.path = self.directory / "session.json"

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        for directory in (self.directory.parent, self.directory):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise VVError(Code.STORAGE_ERROR, "Unsafe OAuth directory.")
            directory.chmod(0o700)
        descriptor = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def read(self):
        for directory in (self.directory.parent, self.directory):
            if directory.is_symlink():
                raise VVError(Code.STORAGE_ERROR, "Unsafe OAuth directory.")
        try:
            return private_read(self.path)
        except FileNotFoundError:
            return None

    def write(self, session):
        descriptor, name = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(session, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self):
        with self.locked():
            session = self.read()
            if session is None:
                return {"auth": "not_configured"}
            return {
                "auth": "expired" if session["expires_at"] <= time.time() else "configured",
                "expires_at": session["expires_at"],
                "refresh_available": bool(session["token"].get("refresh_token")),
            }

    def logout(self):
        with self.locked():
            self.path.unlink(missing_ok=True)
        return {"auth": "not_configured", "remote_revoked": False}


def discover(client):
    try:
        response = client.get("https://mcp.vkusvill.ru/.well-known/oauth-protected-resource/mcp")
        response.raise_for_status()
        resource = ProtectedResourceMetadata.model_validate(response.json())
        response = client.get(ISSUER + ".well-known/oauth-authorization-server")
        response.raise_for_status()
        metadata = OAuthMetadata.model_validate(response.json())
        if (
            str(resource.resource) != RESOURCE
            or [str(value) for value in resource.authorization_servers or []] != [ISSUER]
            or str(metadata.issuer) != ISSUER
            or str(metadata.authorization_endpoint) != ISSUER + "oauth2/auth"
            or str(metadata.token_endpoint) != ISSUER + "oauth2/token"
            or "S256" not in (metadata.code_challenge_methods_supported or [])
            or "authorization_code" not in (metadata.grant_types_supported or [])
        ):
            raise ValueError("Unreviewed OAuth metadata")
        return metadata
    except httpx.HTTPError:
        raise VVError(Code.NETWORK_ERROR, "OAuth discovery unavailable.", retryable=True) from None
    except ValueError:
        raise VVError(
            Code.SCHEMA_CHANGED, "OAuth discovery differs from trusted contract."
        ) from None


def exchange(client, config, data, old_refresh=None):
    data = {**data, "client_id": config.client_id, "resource": RESOURCE}
    auth = None
    if config.token_endpoint_auth_method == "client_secret_basic":
        auth = httpx.BasicAuth(
            quote_plus(config.client_id, safe=""), quote_plus(config.client_secret, safe="")
        )
    elif config.token_endpoint_auth_method == "client_secret_post":
        data["client_secret"] = config.client_secret
    try:
        response = client.post(ISSUER + "oauth2/token", data=data, auth=auth)
        if response.status_code in (400, 401, 403):
            raise VVError(Code.AUTH_REQUIRED, "OAuth grant rejected; explicit login required.")
        response.raise_for_status()
        token = OAuthToken.model_validate(response.json())
        if (
            not token.access_token
            or token.token_type.lower() != "bearer"
            or not token.expires_in
            or token.expires_in <= 0
        ):
            raise ValueError("Invalid token lifetime")
        if old_refresh and token.refresh_token is None:
            token.refresh_token = old_refresh
        return token
    except httpx.HTTPError:
        raise VVError(
            Code.NETWORK_ERROR, "OAuth token endpoint unavailable; do not retry login blindly."
        ) from None
    except ValueError:
        raise VVError(Code.SCHEMA_CHANGED, "OAuth token response is invalid.") from None


def receive_callback(server, redirect_uri, expected_state, timeout):
    server.timeout = 1
    server.result = None
    server.callback_path = urlsplit(redirect_uri).path
    deadline = time.monotonic() + timeout
    while server.result is None and time.monotonic() < deadline:
        server.handle_request()
    if server.result is None:
        raise VVError(Code.AUTH_REQUIRED, "OAuth callback timed out.")
    values = server.result
    if len(values.get("state", [])) != 1 or not hmac.compare_digest(
        values["state"][0].encode(), expected_state.encode()
    ):
        raise VVError(Code.AUTH_REQUIRED, "OAuth callback state mismatch.")
    if "error" in values or len(values.get("code", [])) != 1 or not values["code"][0]:
        raise VVError(Code.AUTH_REQUIRED, "OAuth consent denied or callback invalid.")
    return values["code"][0]


class Callback(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != self.server.callback_path:
            self.send_error(404)
            return
        self.server.result = parse_qs(parsed.query, keep_blank_values=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b"Callback received. Return to your terminal for the result.")

    def log_message(self, *args):
        pass


def login(path, announce, timeout=300):
    config = ClientConfig.model_validate(private_read(path))
    store = AuthStore()
    target = urlsplit(config.redirect_uri)
    with store.locked(), httpx.Client(timeout=20, follow_redirects=False) as client:
        metadata = discover(client)
        if config.token_endpoint_auth_method not in (
            metadata.token_endpoint_auth_methods_supported or []
        ):
            raise VVError(Code.SCHEMA_CHANGED, "Registered client method is no longer advertised.")
        pkce = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)
        query = urlencode(
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
        with HTTPServer(("127.0.0.1", target.port), Callback) as server:
            server.callback_path = target.path
            announce(ISSUER + "oauth2/auth?" + query)
            code = receive_callback(server, config.redirect_uri, state, timeout)
        token = exchange(
            client,
            config,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri,
                "code_verifier": pkce.code_verifier,
            },
        )
        store.write(
            {
                "config": config.model_dump(),
                "token": token.model_dump(),
                "expires_at": time.time() + token.expires_in,
                "context": secrets.token_hex(16),
            }
        )
    return {"auth": "configured"}


@contextmanager
def credentials(endpoint):
    store = AuthStore()
    with store.locked():
        session = store.read()
        if session is None:
            yield {}, "public"
            return
        if endpoint != RESOURCE:
            raise VVError(
                Code.AUTH_REQUIRED, "OAuth credentials cannot be sent to another endpoint."
            )
        if session["expires_at"] <= time.time() + 30:
            refresh = session["token"].get("refresh_token")
            if not refresh:
                raise VVError(Code.AUTH_REQUIRED, "OAuth session expired; explicit login required.")
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                token = exchange(
                    client,
                    ClientConfig.model_validate(session["config"]),
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                    },
                    refresh,
                )
            session.update(token=token.model_dump(), expires_at=time.time() + token.expires_in)
            store.write(session)
        yield {"Authorization": "Bearer " + session["token"]["access_token"]}, session["context"]

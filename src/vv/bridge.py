import json
import os
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from vv.auth import private_read
from vv.errors import Code, VVError
from vv.mcp_provider import TOOLS, MCPProvider


class BrokerProvider(MCPProvider):
    def __init__(self):
        self.endpoint = os.environ.get("VV_BROKER_URL", "")
        parsed = urlsplit(self.endpoint)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
            or not (parsed.scheme == "https" or self.endpoint == "http://vv-auth:8080")
        ):
            raise VVError(
                Code.INVALID_INPUT, "Use HTTPS or the isolated http://vv-auth:8080 sidecar."
            )
        key_file = os.environ.get("VV_BROKER_KEY_FILE")
        if not key_file or os.environ.get("VV_MCP_TEST_URL"):
            raise VVError(
                Code.INVALID_INPUT, "Broker needs a private instance key, not a test URL."
            )
        config = private_read(Path(key_file))
        if set(config) != {"bridge_key"} or not isinstance(config["bridge_key"], str):
            raise VVError(Code.INVALID_INPUT, "Invalid instance credential file.")
        self.key = config["bridge_key"]
        if len(self.key) < 43:
            raise VVError(Code.INVALID_INPUT, "Instance credential is too short.")
        self.schemas = json.loads(files("vv").joinpath("schemas.json").read_text())
        self._context = None

    def request(self, path, data=None, *, mutation=False):
        try:
            with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = client.request(
                    "GET" if data is None else "POST",
                    self.endpoint + path,
                    headers={"Authorization": "Bearer " + self.key},
                    json=data,
                )
            value = response.json()
            if value.get("schema_version") != 1 or type(value.get("ok")) is not bool:
                raise ValueError()
            if not value["ok"]:
                code = Code(value["error"]["code"])
                raise VVError(code, "Auth service rejected request; reconnect or review as needed.")
            response.raise_for_status()
            return value["data"]
        except VVError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            code = Code.OUTCOME_UNKNOWN if mutation else Code.NETWORK_ERROR
            raise VVError(
                code, "Auth service unavailable or invalid response; no automatic retry."
            ) from None

    def status(self):
        result = self.request("/bridge/status")
        if not isinstance(result, dict) or not isinstance(result.get("context"), str):
            raise VVError(Code.SCHEMA_CHANGED, "Invalid auth service status.")
        return result

    @property
    def auth_context(self):
        if self._context is None:
            self._context = self.status()["context"]
        return self._context

    def batch(self, calls):
        mutation = any(name in (TOOLS["link"], TOOLS["personal"]) for name, _ in calls)
        results = self.request(
            "/bridge/call",
            {
                "calls": calls,
                "context": self.auth_context,
                "confirmed": mutation,
            },
            mutation=mutation,
        )
        if (
            not isinstance(results, list)
            or len(results) != len(calls)
            or not all(isinstance(item, dict) for item in results)
        ):
            raise VVError(
                Code.OUTCOME_UNKNOWN if mutation else Code.SCHEMA_CHANGED,
                "Invalid auth service results.",
            )
        return results


def broker_enabled():
    return bool(os.environ.get("VV_BROKER_URL") or os.environ.get("VV_BROKER_KEY_FILE"))

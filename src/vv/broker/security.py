import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode
from urllib.parse import parse_qsl, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vv.errors import Code, VVError

TELEGRAM_PUBLIC_KEY = bytes.fromhex(
    "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_telegram(raw: str, bot_token: str, owner: int, now=None) -> str:
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        if len(values) != len(pairs):
            raise ValueError()
        signature = values.pop("hash")
        message = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        key = hmac.digest(b"WebAppData", bot_token.encode(), "sha256")
        expected = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        encoded = values.pop("signature")
        signed_bytes = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        bot_id = bot_token.split(":", 1)[0]
        check = (
            bot_id
            + ":WebAppData\n"
            + "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        )
        Ed25519PublicKey.from_public_bytes(TELEGRAM_PUBLIC_KEY).verify(signed_bytes, check.encode())
        age = (time.time() if now is None else now) - int(values["auth_date"])
        user = json.loads(values["user"])
        if not 0 <= age <= 120 or type(user.get("id")) is not int or user["id"] != owner:
            raise ValueError()
        if values.get("chat_type") not in (None, "private", "sender"):
            raise ValueError()
        return digest(signed_bytes.hex())
    except (ValueError, KeyError, TypeError, AttributeError, InvalidSignature):
        raise VVError(
            Code.AUTH_REQUIRED, "Open the app from your own bot's private chat."
        ) from None


class WebClient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, repr=False, max_length=4096)
    token_endpoint_auth_method: str
    scope: str = Field(max_length=2048)
    redirect_uri: str

    @model_validator(mode="after")
    def validate_config(self):
        target = urlsplit(self.redirect_uri)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
            or target.path != "/oauth/callback"
        ):
            raise ValueError("An administrator-configured HTTPS callback is required.")
        if self.token_endpoint_auth_method not in (
            "none",
            "client_secret_basic",
            "client_secret_post",
        ):
            raise ValueError("Unsupported client method.")
        if self.token_endpoint_auth_method != "none" and not self.client_secret:
            raise ValueError("Client secret required.")
        if self.token_endpoint_auth_method == "none" and self.client_secret:
            raise ValueError("Public clients must not include a secret.")
        return self

import json
import os
import secrets
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

from vv.auth import private_read
from vv.broker.recovery import private_write
from vv.broker.server import create_app
from vv.broker.service import Broker, Settings


def main():
    root = Path("/state")
    config = root / "broker.json"
    if not config.exists():
        settings = Settings(
            public_origin=os.environ["FIXTURE_ORIGIN"],
            owner_id=int(os.environ["FIXTURE_OWNER"]),
            bot_token=os.environ["FIXTURE_OWNER"] + ":SYNTHETIC-BOT-CANARY-ONLY",
            bridge_key=secrets.token_urlsafe(32),
            encryption_key=Fernet.generate_key().decode(),
            vault_directory=root / "vault",
        )
        private_write(config, settings.model_dump_json().encode())
        private_write(
            Path("/client/bridge.json"), json.dumps({"bridge_key": settings.bridge_key}).encode()
        )
    settings = Settings.model_validate(private_read(config))
    broker = Broker(settings)
    with broker.vault.transaction() as connection:
        if broker.vault.get(connection, "fixture_seeded") is None:
            broker.vault.put(
                connection,
                "account",
                {
                    "config": {
                        "client_id": "synthetic",
                        "client_secret": "SYNTHETIC-SECRET-CANARY",
                    },
                    "token": {
                        "access_token": "SYNTHETIC-ACCESS-CANARY",
                        "refresh_token": "SYNTHETIC-REFRESH-CANARY",
                    },
                    "expires_at": 4102444800,
                    "context": secrets.token_hex(32),
                },
                ttl=None,
            )
            broker.vault.put(connection, "fixture_seeded", True, ttl=None)
    uvicorn.run(
        create_app(broker), host="0.0.0.0", port=8080, access_log=False, log_level="critical"
    )


if __name__ == "__main__":
    main()

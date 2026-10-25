"""Offline installed-package smoke in a read-only, network-disabled broker container."""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet


def main():
    assert os.getuid() != 0
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = {
            "public_origin": "https://synthetic.example",
            "owner_id": 123,
            "bot_token": "123:" + secrets.token_urlsafe(32),
            "bridge_key": secrets.token_urlsafe(32),
            "encryption_key": Fernet.generate_key().decode(),
            "vault_directory": str(root / "vault"),
        }
        config_file = root / "broker.json"
        config_file.write_text(json.dumps(config))
        config_file.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"

        def request(path, *, authorized=False):
            headers = {"Authorization": "Bearer " + config["bridge_key"]} if authorized else {}
            headers["Host"] = "synthetic.example"
            try:
                with urlopen(Request(origin + path, headers=headers), timeout=2) as response:
                    return response.status, response.read().decode()
            except HTTPError as error:
                return error.code, error.read().decode()

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "vv.broker.server",
                "--config",
                str(config_file),
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise AssertionError("Broker exited before readiness")
                try:
                    assert request("/health")[0] == 200
                    break
                except URLError:
                    if time.monotonic() > deadline:
                        raise AssertionError("Broker readiness timeout") from None
                    time.sleep(0.1)
            assert request("/")[0] == 200
            assert request("/assets/connect.js")[0] == 200
            assert request("/connect")[0] == 401
            assert request("/bridge/status")[0] == 401
            status, body = request("/bridge/status", authorized=True)
            assert status == 200
            assert json.loads(body)["data"]["auth"] == "not_configured"
            for name in ("bridge_key", "encryption_key", "bot_token"):
                assert config[name] not in body
            assert request("/bridge/export", authorized=True)[0] == 404
            print(
                "PASS: installed assets, non-root startup, private vault, bridge scope, no export"
            )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()

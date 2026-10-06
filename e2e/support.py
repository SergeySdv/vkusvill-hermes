"""Subprocess isolation shared by protocol tests and the container harness."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def fixture_server(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    control = directory / "control.json"
    journal = directory / "journal.jsonl"
    control.write_text("{}")
    journal.touch()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "e2e.server",
                "--port",
                str(port),
                "--control",
                str(control),
                "--journal",
                str(journal),
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Synthetic MCP exited; inspect server.log")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Synthetic MCP not ready") from None
                    time.sleep(0.05)
            yield {
                "env": {
                    **os.environ,
                    "VV_TEST_MODE": "1",
                    "VV_MCP_TEST_URL": f"http://127.0.0.1:{port}/mcp",
                    "VV_STATE_DIR": str(directory / "state"),
                },
                "control": control,
                "journal": journal,
            }
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def invoke(environment, *arguments):
    result = subprocess.run(
        [sys.executable, "-m", "vv", *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(result.stdout)
    if "SECRET_SENTINEL" in result.stdout + result.stderr:
        raise AssertionError("Provider secret appeared in CLI diagnostics")
    if result.returncode != (0 if payload["ok"] else 1):
        raise AssertionError("CLI exit status contradicts JSON envelope")
    return payload


def read_journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()]

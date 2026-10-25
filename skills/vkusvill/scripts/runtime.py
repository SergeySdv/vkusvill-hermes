import json
import os
import re
import subprocess
from pathlib import Path

REVISION = "d6c72c092ae85ce9ab775209a4da162e96c207fe"
SOURCE = f"git+https://github.com/SergeySdv/vkusvill-hermes.git@{REVISION}"
ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SystemRoot",
    "WINDIR",
    "PATHEXT",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "HERMES_HOME",
    "VV_RUNTIME_ROOT",
    "VV_STATE_DIR",
    "VV_PROFILE",
    "VV_BROKER_URL",
    "VV_BROKER_KEY_FILE",
    "VV_PILOT_MANIFEST",
    "VV_TEST_MODE",
    "VV_MCP_TEST_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "PIP_CERT",
)


def runtime_root() -> Path:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return (
        Path(os.environ.get("VV_RUNTIME_ROOT", str(hermes_home / "integrations/vkusvill")))
        .expanduser()
        .resolve()
    )


def runtime_python() -> Path:
    revision, _ = runtime_identity()
    return runtime_root() / revision / "bin/python"


def runtime_identity() -> tuple[str, str]:
    manifest = os.environ.get("VV_PILOT_MANIFEST")
    if not manifest:
        return REVISION, SOURCE
    value = json.loads(Path(manifest).read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid administrator pilot manifest.")
    digest = value.get("wheel_sha256", "")
    if (
        set(value) != {"wheel_sha256"}
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
    ):
        raise ValueError("Invalid administrator pilot manifest.")
    return "pilot-" + digest, "wheel:sha256:" + digest


def runtime_environment() -> dict[str, str]:
    environment = {}
    for name in ENVIRONMENT_ALLOWLIST:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    environment.setdefault("PATH", os.defpath)
    environment.setdefault("VV_STATE_DIR", str(runtime_root() / "state"))
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def run(arguments: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=runtime_environment(),
    )


def ready() -> bool:
    try:
        revision, source = runtime_identity()
        marker = json.loads((runtime_root() / revision / "ready.json").read_text())
        return marker == {"revision": revision, "source": source} and runtime_python().is_file()
    except (OSError, ValueError):
        return False


def doctor() -> dict:
    result = run([str(runtime_python()), "-m", "vv", "doctor", "--json"], timeout=120)
    payload = json.loads(result.stdout)
    if payload.get("ok") is not True or payload.get("schema_version") != 1:
        raise ValueError("CLI doctor failed.")
    return payload

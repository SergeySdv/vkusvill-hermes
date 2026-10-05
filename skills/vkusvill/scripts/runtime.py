import json
import os
import subprocess
from pathlib import Path

REVISION = "265b0311bbcf584c3f147893217b38c069c7e3b6"
SOURCE = f"git+https://github.com/SergeySdv/vkusvill-hermes.git@{REVISION}"


def runtime_root() -> Path:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return (
        Path(os.environ.get("VV_RUNTIME_ROOT", str(hermes_home / "integrations/vkusvill")))
        .expanduser()
        .resolve()
    )


def runtime_python() -> Path:
    return runtime_root() / REVISION / "bin/python"


def runtime_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("VV_STATE_DIR", str(runtime_root() / "state"))
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
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
        marker = json.loads((runtime_root() / REVISION / "ready.json").read_text())
        return marker == {"revision": REVISION, "source": SOURCE} and runtime_python().is_file()
    except (OSError, ValueError):
        return False


def doctor() -> dict:
    result = run([str(runtime_python()), "-m", "vv", "doctor", "--live", "--json"], timeout=120)
    payload = json.loads(result.stdout)
    if payload.get("ok") is not True or payload.get("schema_version") != 1:
        raise ValueError("CLI doctor failed.")
    return payload

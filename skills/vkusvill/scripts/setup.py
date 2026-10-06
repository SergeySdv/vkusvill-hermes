"""Explicit installation entry point; normal skill usage never installs software."""

import json
import os
import shutil
import subprocess
import sys

from runtime import REVISION, SOURCE, doctor, ready, run, runtime_python, runtime_root


def install() -> dict:
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required.")
    reused = ready()
    if not reused:
        if shutil.which("git") is None:
            raise RuntimeError("Git is required to install the pinned CLI source.")
        destination = runtime_python().parent.parent
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        print("Installing isolated vv runtime; this can take a few minutes.", file=sys.stderr)
        run([sys.executable, "-m", "venv", str(destination)])
        run(
            [
                str(runtime_python()),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                SOURCE,
            ]
        )
    result = doctor()
    marker = runtime_root() / REVISION / "ready.json"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps({"revision": REVISION, "source": SOURCE}) + "\n")
    os.replace(temporary, marker)
    return {
        "ok": True,
        "reused": reused,
        "revision": REVISION,
        "runtime_python": str(runtime_python()),
        "doctor": result,
        "capabilities": "ten_mcp_adapters_oauth_not_configured",
    }


def main() -> int:
    try:
        result = install()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "SETUP_FAILED",
                    "message": (
                        "Check Python 3.11+, venv/pip, Git, writable Hermes home and access "
                        "to GitHub/Python package index; then rerun setup."
                    ),
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

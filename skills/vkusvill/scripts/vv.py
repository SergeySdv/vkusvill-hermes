"""Run the pinned CLI without depending on the shell PATH."""

import json
import os
import sys

from runtime import ready, runtime_environment, runtime_python


def main() -> int:
    if not ready():
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "SETUP_REQUIRED",
                        "message": "Run scripts/setup.py for this skill after an install request.",
                        "retryable": False,
                    },
                    "warnings": [],
                    "meta": {"component": "skill_launcher"},
                }
            )
        )
        return 1
    python = str(runtime_python())
    os.execve(python, [python, "-m", "vv", *sys.argv[1:]], runtime_environment())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

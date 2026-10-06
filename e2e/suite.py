"""Repeat all model scenarios without masking failures with retries."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("Choose 1–10 independent repetitions")
    scenarios = json.loads(Path(__file__).with_name("scenarios.json").read_text())
    runs = []
    for repetition in range(args.repeats):
        for scenario in scenarios:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "e2e.docker",
                    "agent",
                    "--scenario",
                    scenario["name"],
                    "--env-file",
                    str(args.env_file),
                ],
                check=False,
            )
            runs.append(
                {
                    "scenario": scenario["name"],
                    "repetition": repetition + 1,
                    "exit_code": result.returncode,
                }
            )
    print(json.dumps({"runs": runs, "passed": all(run["exit_code"] == 0 for run in runs)}))
    return 0 if all(run["exit_code"] == 0 for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())

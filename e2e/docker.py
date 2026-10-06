"""Disposable containers; only explicitly supplied test credentials enter them."""

import argparse
import json
import subprocess
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=["smoke", "agent", "install", "candidate-install", "release"]
    )
    parser.add_argument(
        "--scenario",
        choices=["search", "basket", "unknown", "price-change", "uncertain"],
        default="basket",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--image", default="vkusvill-hermes-e2e")
    args = parser.parse_args()
    if args.mode == "agent" and args.env_file is None:
        parser.error("Agent mode requires an explicit --env-file with test-only model credentials")
    if args.env_file and args.mode != "agent":
        parser.error("Credentials are only accepted for explicit model evaluations")
    if args.env_file and (not args.env_file.is_file() or args.env_file.stat().st_mode & 0o077):
        parser.error("Credential file must exist and have owner-only permissions")
    name = "vv-e2e-" + uuid.uuid4().hex[:12]
    output = Path(".e2e-results") / name
    output.mkdir(parents=True, mode=0o700)
    command = [
        "docker",
        "create",
        "--name",
        name,
        "--init",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "4g",
        "--cpus",
        "2",
        "--entrypoint",
        "/opt/vv/bin/python",
    ]
    if args.env_file:
        command += ["--env-file", str(args.env_file.resolve())]
    if args.mode == "release":
        command += [args.image, "-m", "e2e.release"]
    else:
        command += [args.image, "-m", "e2e.run", args.mode, "--scenario", args.scenario]
    timeout = 1800 if args.mode == "release" else 420
    created = False
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        created = True
        image = subprocess.run(
            ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (output / "image.json").write_text(json.dumps({"image_id": image}))
        with (output / "container.log").open("w") as log:
            result = subprocess.run(
                ["docker", "start", "--attach", name], stdout=log, stderr=log, timeout=timeout
            )
        subprocess.run(
            ["docker", "cp", f"{name}:/opt/data/results/.", str(output)],
            capture_output=True,
            check=False,
        )
        report = output / "result.json"
        if report.exists():
            print(report.read_text())
        else:
            print("No evaluation report; inspect the private container.log.")
        print(f"Artifacts: {output}")
        return result.returncode if report.exists() else 2
    except subprocess.TimeoutExpired:
        print(f"Container exceeded {timeout} seconds; evaluation failed.")
        return 124
    finally:
        if created:
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", name],
                capture_output=True,
                check=False,
                timeout=30,
            )


if __name__ == "__main__":
    raise SystemExit(main())

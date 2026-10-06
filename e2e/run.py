"""Run inside the disposable Hermes image, never against the user's real profile."""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from e2e.grade import grade
from e2e.support import fixture_server, read_journal

ROOT = Path("/opt/candidate")
HERMES = "/opt/hermes/.venv/bin/hermes"


def prepare_home(home: Path):
    home.mkdir(parents=True, exist_ok=True)
    skill = home / "skills/vkusvill"
    shutil.copytree(ROOT / "skills/vkusvill", skill)
    runtime = skill / "scripts/runtime.py"
    sources = sorted(
        [
            *(ROOT / "src/vv").glob("*.py"),
            ROOT / "src/vv/schemas.json",
            ROOT / "uv.lock",
            *(
                path
                for path in (ROOT / "skills/vkusvill").rglob("*")
                if path.is_file() and path.suffix in (".py", ".md")
            ),
        ]
    )
    revision = (
        "candidate-"
        + hashlib.sha256(
            b"".join(
                str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() for path in sources
            )
        ).hexdigest()[:16]
    )
    source = "file:///opt/candidate"
    lines = runtime.read_text().splitlines()
    runtime.write_text(
        "\n".join(
            f"REVISION = {revision!r}"
            if line.startswith("REVISION = ")
            else f"SOURCE = {source!r}"
            if line.startswith("SOURCE = ")
            else line
            for line in lines
        )
        + "\n"
    )
    installed = home / "integrations/vkusvill" / revision
    (installed / "bin").mkdir(parents=True)
    (installed / "bin/python").symlink_to(sys.executable)
    shutil.copy(Path(sys.prefix) / "pyvenv.cfg", installed / "pyvenv.cfg")
    (installed / "lib").symlink_to(Path(sys.prefix) / "lib", target_is_directory=True)
    (installed / "ready.json").write_text(json.dumps({"revision": revision, "source": source}))
    (home / "config.yaml").write_text(
        "terminal:\n  backend: local\n  cwd: /opt/data/workspace\n"
        "agent:\n  max_turns: 25\n  run_budget_seconds: 240\n"
    )
    return revision


def execute(arguments, environment, output, error, timeout=300):
    with output.open("w") as stdout, error.open("w") as stderr:
        process = subprocess.Popen(
            arguments,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            cwd="/opt/data/workspace",
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return 124


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "agent", "install", "candidate-install"])
    parser.add_argument(
        "--scenario",
        choices=["search", "basket", "unknown", "price-change", "uncertain"],
        default="basket",
    )
    parser.add_argument("--output", type=Path, default=Path("/opt/data/results"))
    args = parser.parse_args()
    if not ROOT.is_dir() or os.environ.get("HERMES_HOME") != "/opt/data":
        parser.error("Use the disposable E2E Docker image; do not run on a personal profile")
    if args.mode == "agent" and not os.environ.get("E2E_MODEL"):
        print(
            json.dumps({"status": "blocked", "reason": "E2E_MODEL and provider credentials needed"})
        )
        return 2
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    home = Path("/opt/data/test-home")
    Path("/opt/data/workspace").mkdir()
    if args.mode in ("install", "candidate-install"):
        home.mkdir()
        environment = {**os.environ, "HERMES_HOME": str(home), "HOME": "/opt/data"}
        environment.pop("VV_MCP_TEST_URL", None)
        environment.pop("VV_TEST_MODE", None)
        commands = [
            [HERMES, "skills", "install", "SergeySdv/vkusvill-hermes/skills/vkusvill"],
            [sys.executable, str(home / "skills/vkusvill/scripts/setup.py")],
            [
                sys.executable,
                str(home / "skills/vkusvill/scripts/vv.py"),
                "doctor",
                "--live",
                "--json",
            ],
        ]
        if args.mode == "candidate-install":
            commands[0] = [
                str(Path(HERMES).with_name("python")),
                str(ROOT / "e2e/install_candidate.py"),
            ]
        codes = []
        failure_stage = None
        for index, command in enumerate(commands):
            codes.append(
                execute(
                    command,
                    environment,
                    args.output / f"install-{index}.out",
                    args.output / f"install-{index}.err",
                    timeout=90,
                )
            )
            if codes[-1] != 0:
                failure_stage = ["skill_install", "runtime_setup", "live_doctor"][index]
                break
            if index == 0 and not (home / "skills/vkusvill/scripts/setup.py").is_file():
                failure_stage = "skill_install_blocked_or_missing"
                break
        reused = False
        if codes == [0, 0, 0]:
            repeat_code = execute(
                commands[1],
                environment,
                args.output / "setup-repeat.out",
                args.output / "setup-repeat.err",
                timeout=90,
            )
            try:
                repeated = json.loads((args.output / "setup-repeat.out").read_text())
                reused = (
                    repeat_code == 0
                    and repeated.get("ok") is True
                    and repeated.get("reused") is True
                )
            except ValueError:
                pass
            if not reused:
                failure_stage = "runtime_setup_idempotency"
        doctor = {}
        if codes == [0, 0, 0]:
            try:
                doctor = json.loads((args.output / "install-2.out").read_text())
            except ValueError:
                pass
        result = {
            "passed": codes == [0, 0, 0] and doctor.get("ok") is True and reused,
            "runtime_setup_reused": reused,
            "mode": (
                "clean_install_published_release"
                if args.mode == "install"
                else "local_candidate_guarded_install_pinned_cli"
            ),
            "llm_tested": False,
            "candidate_tested": args.mode == "candidate-install",
            "github_skill_download_tested": args.mode == "install",
            "exit_codes": codes,
            "failure_stage": failure_stage,
        }
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return 0 if result["passed"] else 1
    revision = prepare_home(home)
    with fixture_server(Path("/opt/data/fixture")) as fixture:
        environment = {
            **fixture["env"],
            "HERMES_HOME": str(home),
            "HOME": "/opt/data",
            "TERMINAL_ENV": "local",
        }
        launcher = home / "skills/vkusvill/scripts/vv.py"
        if args.mode == "smoke":
            commands = [
                [HERMES, "--version"],
                [HERMES, "skills", "list"],
                [sys.executable, str(launcher), "doctor", "--live", "--json"],
                [
                    str(Path(HERMES).with_name("python")),
                    str(ROOT / "e2e/install_candidate.py"),
                    "--scan-only",
                ],
            ]
            codes = [
                execute(
                    command,
                    environment,
                    args.output / f"smoke-{index}.out",
                    args.output / f"smoke-{index}.err",
                    timeout=60,
                )
                for index, command in enumerate(commands)
            ]
            try:
                doctor = json.loads((args.output / "smoke-2.out").read_text())
            except ValueError:
                doctor = {}
            result = {
                "passed": codes == [0, 0, 0, 0]
                and doctor.get("ok") is True
                and "vkusvill" in (args.output / "smoke-1.out").read_text(),
                "mode": "preinstalled_smoke",
                "llm_tested": False,
                "exit_codes": codes,
            }
        else:
            scenario = next(
                item
                for item in json.loads((ROOT / "e2e/scenarios.json").read_text())
                if item["name"] == args.scenario
            )
            fixture["control"].write_text(json.dumps(scenario["fixture"]))
            query = args.output / "query.txt"
            query.write_text(scenario["prompt"])
            command = [
                HERMES,
                "chat",
                "--oneshot",
                "--query-file",
                str(query),
                "--format",
                "stream-json",
                "--max-turns",
                "25",
                "--run-budget",
                "240",
                "--toolsets",
                "terminal,skills",
                "--model",
                os.environ["E2E_MODEL"],
            ]
            if os.environ.get("E2E_PROVIDER"):
                command += ["--provider", os.environ["E2E_PROVIDER"]]
            code = execute(
                command, environment, args.output / "trace.jsonl", args.output / "stderr.log"
            )
            events = []
            for line in (args.output / "trace.jsonl").read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
            result = grade(
                scenario["expected"],
                events,
                read_journal(fixture["journal"]),
                Path(environment["VV_STATE_DIR"]),
            )
            result.update(
                {
                    "passed": result["passed"] and code == 0,
                    "exit_code": code,
                    "scenario": args.scenario,
                    "mode": "real_llm_synthetic_mcp",
                    "model": os.environ["E2E_MODEL"],
                    "provider": os.environ.get("E2E_PROVIDER", "auto"),
                }
            )
        result["candidate_runtime"] = revision
        shutil.copy(fixture["journal"], args.output / "mcp.jsonl")
        (args.output / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Release gate: pristine skill, actual pinned installs and previous-version state."""

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from e2e.support import fixture_server, read_journal

ROOT = Path("/opt/candidate")
HOME = Path("/opt/data/test-home")
BASELINE = "36542199c79bb107c8b46d8f2d91909655bf8fbd"
REPOSITORY = "https://github.com/SergeySdv/vkusvill-hermes.git"


def revision_of(skill: Path) -> str:
    tree = ast.parse((skill / "scripts/runtime.py").read_text())
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "REVISION" for target in statement.targets
        ):
            revision = ast.literal_eval(statement.value)
            if isinstance(revision, str) and len(revision) == 40:
                int(revision, 16)
                return revision
    raise ValueError("Expected an immutable CLI commit pin")


def tree_digest(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in (".py", ".json")
    }


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_identity(probe: dict, revision: str, version: str, expected_files: dict):
    require(probe["version"] == version, "Installed version differs from checkout")
    require(probe["origin"]["vcs_info"]["commit_id"] == revision, "Wrong installed commit")
    require(probe["files"] == expected_files, "Pin points at different CLI code")


def run_gate(output: Path) -> dict:
    require(ROOT.is_dir() and os.environ.get("HERMES_HOME") == "/opt/data", "Disposable image only")
    require(not HOME.exists(), "Expected a fresh disposable profile")
    output.mkdir(parents=True, exist_ok=False)
    skill = HOME / "skills/vkusvill"
    candidate = ROOT / "skills/vkusvill"
    revision = revision_of(candidate)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    result = {
        "passed": False,
        "mode": "release_gate",
        "expected_revision": revision,
        "expected_version": version,
        "baseline_skill_revision": BASELINE,
        "pin_rewritten": False,
        "llm_tested": False,
        "github_skill_download_tested": False,
        "checks": [],
    }
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": "/opt/data",
        "HERMES_HOME": str(HOME),
        "PYTHONNOUSERSITE": "1",
    }
    counter = 0

    def command(arguments, env=None, expected=0, decode=True):
        nonlocal counter
        counter += 1
        completed = subprocess.run(
            arguments, env=env or environment, capture_output=True, text=True, timeout=240
        )
        (output / f"step-{counter}.out").write_text(completed.stdout)
        (output / f"step-{counter}.err").write_text(completed.stderr)
        require(completed.returncode == expected, f"Unexpected exit at release step {counter}")
        return json.loads(completed.stdout) if decode else completed.stdout

    def install_skill():
        installed = command(
            ["/opt/hermes/.venv/bin/python", str(ROOT / "e2e/install_candidate.py")]
        )
        require(installed["allowed"] is True, "Native scanner rejected candidate")
        for path in candidate.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                require(
                    (skill / path.relative_to(candidate)).read_bytes() == path.read_bytes(),
                    "Installed skill bytes differ from candidate",
                )

    def setup(env=None, expected=0):
        return command([sys.executable, str(skill / "scripts/setup.py")], env, expected)

    def cli(*arguments, env=None, expected=0, launcher=None):
        return command(
            [sys.executable, str(launcher or skill / "scripts/vv.py"), *arguments], env, expected
        )

    def verify_runtime():
        python = HOME / "integrations/vkusvill" / revision / "bin/python"
        probe = command(
            [
                str(python),
                "-c",
                "import hashlib,importlib.metadata as metadata,json,pathlib,vv; "
                "root=pathlib.Path(vv.__file__).parent; "
                "distribution=metadata.distribution('vkusvill-hermes'); "
                "print(json.dumps({'version':distribution.version,"
                "'origin':json.loads(distribution.read_text('direct_url.json')),"
                "'files':{str(path.relative_to(root)):"
                "hashlib.sha256(path.read_bytes()).hexdigest() "
                "for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts "
                "and path.suffix in ('.py','.json')}}))",
            ]
        )
        verify_identity(probe, revision, version, tree_digest(ROOT / "src/vv"))
        require(cli("--json", "--version")["data"]["version"] == version, "Wrong launcher version")

    def new_commands(fixture):
        env = {
            **environment,
            "VV_TEST_MODE": "1",
            "VV_MCP_TEST_URL": fixture["env"]["VV_MCP_TEST_URL"],
        }
        for arguments in [
            ["product", "barcode", "0012345678901"],
            ["discount", "search"],
            ["recipe", "search"],
            ["shop", "search"],
            ["orders", "list"],
            ["favorite", "show"],
        ]:
            require(cli(*arguments, env=env)["ok"] is True, "Installed command failed")
        require(
            {
                "vkusvill_product_barcode",
                "vkusvill_products_discount",
                "vkusvill_recipes",
                "vkusvill_shops",
                "vkusvill_orders_history",
                "vkusvill_product_lp",
            }.issubset({event["name"] for event in read_journal(fixture["journal"])}),
            "Commands did not reach all six MCP tools",
        )

    try:
        HOME.mkdir()
        install_skill()
        first = setup()
        require(first["ok"] and not first["reused"], "Fresh setup was not fresh")
        verify_runtime()
        with fixture_server(output / "clean-fixture") as fixture:
            new_commands(fixture)
        require(setup()["reused"] is True, "Repeated setup reinstalled runtime")
        result["checks"].append("clean_install_and_repeat")

        shutil.rmtree(HOME)
        HOME.mkdir()
        baseline = output / "baseline"
        command(
            ["git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(baseline)], decode=False
        )
        command(["git", "-C", str(baseline), "checkout", "--quiet", BASELINE], decode=False)
        shutil.copytree(baseline / "skills/vkusvill", skill)
        old_revision = revision_of(skill)
        require(old_revision != revision, "Upgrade must cross CLI revisions")
        require(setup()["ok"] is True, "Previous CLI setup failed")
        old_skill = output / "previous-skill"
        shutil.copytree(skill, old_skill)
        old_launcher = old_skill / "scripts/vv.py"
        request = output / "request.json"
        request.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "items": [{"product_id": 101, "quantity": "2", "unit": "package"}],
                    "constraints": {"currency": "RUB", "max_goods_total": "300"},
                }
            )
        )
        for profile in ("default", "other"):
            env = {**environment, "VV_PROFILE": profile}
            require(
                cli("basket", "import", "upgrade", "--file", str(request), env=env)["ok"],
                "Import failed",
            )
        before = cli("basket", "show", "upgrade")["data"]
        state = HOME / "integrations/vkusvill/state/baskets.sqlite3"
        state_before = state.read_bytes()
        old_marker = HOME / "integrations/vkusvill" / old_revision / "ready.json"
        marker_before = old_marker.read_bytes()
        install_skill()
        shutil.rmtree(Path("/opt/data/.cache/pip"), ignore_errors=True)
        failed_env = {
            **environment,
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }
        require(setup(failed_env, expected=1)["ok"] is False, "Broken download should fail")
        marker = HOME / "integrations/vkusvill" / revision / "ready.json"
        require(
            not list(marker.parent.rglob("vkusvill_hermes-*.dist-info")),
            "Download failure was masked by a cached installation",
        )
        require(not marker.exists(), "Failed runtime incorrectly marked ready")
        require(state.read_bytes() == state_before, "Failed install changed baskets")
        require(old_marker.read_bytes() == marker_before, "Failed install changed previous runtime")
        require(
            cli("basket", "show", "upgrade", launcher=old_launcher)["data"] == before,
            "Previous launcher no longer works",
        )
        require(
            cli("doctor", expected=1)["error"]["code"] == "SETUP_REQUIRED",
            "Candidate silently launched wrong runtime",
        )
        result["checks"].append("failed_download_preserves_previous_runtime_and_baskets")

        with fixture_server(output / "upgrade-fixture") as fixture:
            env = {
                **environment,
                "VV_TEST_MODE": "1",
                "VV_MCP_TEST_URL": fixture["env"]["VV_MCP_TEST_URL"],
            }
            fixture["control"].write_text('{"auth_required": true}')
            require(setup(env, expected=1)["ok"] is False, "Failed doctor should fail setup")
            require(not marker.exists(), "Failed doctor marked runtime ready")
            require(
                list(marker.parent.rglob("vkusvill_hermes-*.dist-info")),
                "Doctor failure test did not install the package",
            )
            require(state.read_bytes() == state_before, "Failed doctor changed baskets")
            require(old_marker.read_bytes() == marker_before, "Doctor failure changed old runtime")
            fixture["control"].write_text("{}")
            require(setup(env)["ok"] is True, "Recovery failed")
            verify_runtime()
            for profile in ("default", "other"):
                require(
                    cli("basket", "show", "upgrade", env={**env, "VV_PROFILE": profile})["data"]
                    == before,
                    "Upgrade lost or changed a basket",
                )
            new_commands(fixture)
            checked = cli("basket", "check", "upgrade", "--refresh", env=env)
            require(checked["data"]["state"] == "checked", "Upgraded basket cannot be checked")
            marker_before_repeat = marker.read_bytes()
            require(setup(env)["reused"] is True, "Upgraded runtime was not reused")
            require(marker.read_bytes() == marker_before_repeat, "Repeat changed runtime marker")
            require(
                cli("basket", "show", "upgrade", env=env)["data"] == checked["data"],
                "Repeat changed basket",
            )
        result["checks"] += [
            "failed_doctor_not_ready",
            "upgrade_preserves_profiles_and_baskets",
            "new_commands_from_pinned_runtime",
            "repeat_preserves_checked_basket",
        ]
        result["baseline_cli_revision"] = old_revision
        result["passed"] = True
    except Exception as error:
        result["failure_type"] = type(error).__name__
        result["failure_step"] = counter
        if isinstance(error, AssertionError):
            result["failure_reason"] = str(error)
    finally:
        (output / "result.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    os.umask(0o077)
    report = run_gate(Path("/opt/data/results"))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)

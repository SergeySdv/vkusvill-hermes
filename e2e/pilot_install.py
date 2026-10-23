"""Run only in a disposable Hermes container with /bundle mounted read-only."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    home = Path("/opt/data/test-home")
    if os.environ.get("HERMES_HOME") != str(home) or home.exists():
        raise RuntimeError("Fresh disposable profile required.")
    sys.path.insert(0, "/opt/hermes")
    spec = importlib.util.spec_from_file_location("pilot", "/bundle/install_pilot.py")
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    skill = home / "skills/vkusvill"
    baseline = Path("/baseline/skills/vkusvill")
    legacy = baseline.is_dir()
    if legacy:
        shutil.copytree(baseline, skill)
        subprocess.run(
            [sys.executable, str(skill / "scripts/setup.py")],
            check=True,
            capture_output=True,
            timeout=600,
        )
        result = subprocess.run(
            [sys.executable, str(skill / "scripts/vv.py"), "--version", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)["data"]["version"] == "0.4.0"
    else:
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("Previous skill preserved exactly\n")
    previous_skill = (skill / "SKILL.md").read_bytes()
    state = home / "integrations/vkusvill/state"
    state.mkdir(parents=True, exist_ok=True)
    basket = state / "basket-preservation-canary.json"
    basket.write_text('{"synthetic":"prior basket bytes and links must not change"}')
    expected = hashlib.sha256(basket.read_bytes()).hexdigest()
    if legacy:
        request = home / "synthetic-request.json"
        request.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "items": [{"product_id": 123456789, "quantity": "2", "unit": "package"}],
                    "constraints": {},
                }
            )
        )
        subprocess.run(
            [
                sys.executable,
                str(skill / "scripts/vv.py"),
                "basket",
                "import",
                "pilot_upgrade",
                "--file",
                str(request),
                "--json",
            ],
            check=True,
            capture_output=True,
        )
        original = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts/vv.py"),
                "basket",
                "show",
                "pilot_upgrade",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        original_basket = json.loads(original.stdout)["data"]
    first = pilot.install(Path("/bundle"), home)
    second = pilot.install(Path("/bundle"), home)
    assert first["ok"] and first["prior_skill"] and second["reused"]
    assert hashlib.sha256(basket.read_bytes()).hexdigest() == expected
    digest = first["wheel_sha256"]
    backup = home / "integrations/vkusvill" / ("skill-before-" + digest)
    assert (backup / "SKILL.md").read_bytes() == previous_skill
    manifest = home / "pilot.json"
    manifest.write_text(json.dumps({"wheel_sha256": digest}))
    environment = {**os.environ, "VV_PILOT_MANIFEST": str(manifest)}
    for arguments in (("--version", "--json"), ("doctor", "--json")):
        result = subprocess.run(
            [sys.executable, str(skill / "scripts/vv.py"), *arguments],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)["ok"]
    if legacy:
        result = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts/vv.py"),
                "basket",
                "show",
                "pilot_upgrade",
                "--json",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)["data"] == original_basket
    (skill / "SKILL.md").write_text("tampered")
    try:
        pilot.install(Path("/bundle"), home)
    except ValueError:
        pass
    else:
        raise AssertionError("Tampered skill was accepted")
    print(
        json.dumps(
            {
                "ok": True,
                "native_scanner": "passed",
                "repeated_install": "passed",
                "prior_skill_preserved": True,
                "state_unchanged": True,
                "tamper_rejected": True,
                "release_pin_changed": False,
                "actual_legacy_runtime_upgrade_tested": legacy,
            }
        )
    )


if __name__ == "__main__":
    main()

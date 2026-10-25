"""Administrator-only candidate installation; never changes the published Git pin."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_bundle(bundle):
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise ValueError("Symlink bundle member.")
    manifest = json.loads((bundle / "pilot.json").read_text())
    if set(manifest) != {"schema_version", "files", "wheel"} or manifest["schema_version"] != 1:
        raise ValueError("Unsupported bundle.")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe bundle path.")
        path = bundle / relative
        if any(part.is_symlink() for part in (path, *path.parents)) or digest(path) != expected:
            raise ValueError("Bundle integrity failure.")
    wheel = manifest["wheel"]
    if wheel not in manifest["files"] or not wheel.endswith(".whl"):
        raise ValueError("Missing wheel.")
    required = {"requirements.txt", "skill/SKILL.md", "skill/scripts/runtime.py"}
    if not required.issubset(manifest["files"]):
        raise ValueError("Incomplete bundle.")
    actual = {
        str(path.relative_to(bundle)) for path in (bundle / "skill").rglob("*") if path.is_file()
    }
    if actual != {name for name in manifest["files"] if name.startswith("skill/")}:
        raise ValueError("Unmanifested skill files.")
    return manifest


def execute(arguments, environment):
    subprocess.run(arguments, env=environment, check=True, capture_output=True, timeout=600)


def install(bundle, home):
    manifest = checked_bundle(bundle)
    from tools.skills_guard import scan_skill_cached, should_allow_install

    scan, _ = scan_skill_cached(bundle / "skill", source="community")
    allowed, _ = should_allow_install(scan, force=False)
    if not allowed:
        raise ValueError("Native Hermes scanner rejected pilot.")
    wheel_hash = manifest["files"][manifest["wheel"]]
    root = home / "integrations/vkusvill"
    runtime = root / ("pilot-" + wheel_hash)
    skill = home / "skills/vkusvill"
    backup = root / ("skill-before-" + wheel_hash)
    marker = {"revision": runtime.name, "source": "wheel:sha256:" + wheel_hash}
    environment = {
        name: os.environ[name] for name in ("PATH", "HOME", "LANG") if name in os.environ
    }
    environment.update(
        HERMES_HOME=str(home),
        VV_STATE_DIR=str(root / "state"),
        PYTHONNOUSERSITE="1",
        PIP_CONFIG_FILE=os.devnull,
    )
    root.mkdir(parents=True, exist_ok=True)
    for target in (home, root, runtime, skill, backup):
        if any(part.is_symlink() for part in (target, *target.parents)):
            raise ValueError("Symlink installation target.")
    python = runtime / "bin/python"
    reused = (runtime / "ready.json").is_file()
    if reused:
        if json.loads((runtime / "ready.json").read_text()) != marker:
            raise ValueError("Pilot marker mismatch.")
    else:
        if runtime.exists():
            raise ValueError("Incomplete runtime exists; inspect it before retrying.")
        execute([sys.executable, "-m", "venv", str(runtime)], environment)
        execute(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "--index-url",
                "https://pypi.org/simple",
                "-r",
                str(bundle / "requirements.txt"),
            ],
            environment,
        )
        execute(
            [str(python), "-m", "pip", "install", "--no-deps", str(bundle / manifest["wheel"])],
            environment,
        )
        execute([str(python), "-m", "pip", "check"], environment)
        execute([str(python), "-m", "vv", "doctor", "--json"], environment)
        (runtime / "ready.json").write_text(json.dumps(marker))
    active_marker = skill / ".pilot-wheel"
    if active_marker.is_file() and active_marker.read_text() == wheel_hash:
        for name, expected in manifest["files"].items():
            if (
                name.startswith("skill/")
                and digest(skill / name.removeprefix("skill/")) != expected
            ):
                raise ValueError("Installed pilot skill changed; review before reinstalling.")
        return {"ok": True, "reused": True, "wheel_sha256": wheel_hash}
    if backup.exists():
        raise ValueError("Prior pilot rollback exists; inspect before replacing skill.")
    stage = root / ("skill-stage-" + wheel_hash)
    if stage.exists():
        raise ValueError("Prior staging directory exists.")
    shutil.copytree(bundle / "skill", stage)
    (stage / ".pilot-wheel").write_text(wheel_hash)
    skill.parent.mkdir(parents=True, exist_ok=True)
    existed = skill.exists()
    if existed:
        skill.rename(backup)
    try:
        stage.rename(skill)
    except BaseException:
        if existed:
            backup.rename(skill)
        raise
    return {
        "ok": True,
        "reused": reused,
        "wheel_sha256": wheel_hash,
        "prior_skill": existed,
        "release_pin_changed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.bundle, args.home)))
    except Exception:
        parser.exit(1, "Pilot install failed; details suppressed. Inspect private state.\n")


if __name__ == "__main__":
    main()

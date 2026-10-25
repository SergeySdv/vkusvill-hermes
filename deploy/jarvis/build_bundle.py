"""Build a checksummed, unpublished pilot; does not change the release pin."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError("Use a new destination.")
    destination.mkdir(mode=0o700, parents=True)
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(destination)], cwd=ROOT, check=True)
    requirements = subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    (destination / "requirements.txt").write_bytes(requirements)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "skills/vkusvill", destination / "skill", ignore=ignore)
    shutil.copy2(ROOT / "deploy/jarvis/install_pilot.py", destination)
    shutil.copy2(ROOT / "deploy/jarvis/Caddyfile.site", destination)
    shutil.copy2(ROOT / "deploy/jarvis/compose.yaml", destination)
    context = destination / "image"
    context.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy2(ROOT / name, context / name)
    shutil.copytree(ROOT / "src", context / "src", ignore=ignore)
    shutil.copy2(ROOT / "deploy/broker/Dockerfile", context / "Dockerfile")
    wheels = list(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected one wheel.")
    manifest = {
        "schema_version": 1,
        "wheel": wheels[0].name,
        "files": {
            str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(destination.rglob("*"))
            if path.is_file()
        },
    }
    (destination / "pilot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "bundle": str(destination),
                "manifest_sha256": hashlib.sha256(
                    (destination / "pilot.json").read_bytes()
                ).hexdigest(),
                "published": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output.resolve())

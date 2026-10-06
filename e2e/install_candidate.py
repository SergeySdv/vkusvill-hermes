"""Test local skill bytes through Hermes quarantine, policy and installation APIs."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-only", action="store_true")
    args = parser.parse_args()
    if os.environ.get("HERMES_HOME") != "/opt/data/test-home":
        raise RuntimeError("Disposable test profile required")
    sys.path.insert(0, "/opt/hermes")
    from tools.skills_guard import scan_skill_cached, should_allow_install
    from tools.skills_hub import _quarantine_dir
    from tools.skills_hub_install import install_from_quarantine
    from tools.skills_hub_models import SkillBundle

    source = Path("/opt/candidate/skills/vkusvill")
    quarantine = _quarantine_dir() / "vkusvill"
    shutil.copytree(source, quarantine)
    scan, provenance = scan_skill_cached(quarantine, source="community")
    allowed, reason = should_allow_install(scan, force=False)
    result = {
        "allowed": allowed,
        "verdict": scan.verdict,
        "reason": reason,
        "provenance": provenance,
        "github_download_tested": False,
    }
    if allowed is not True:
        print(json.dumps(result))
        return 1
    if args.scan_only:
        print(json.dumps(result))
        return 0
    bundle = SkillBundle(
        name="vkusvill",
        source="community",
        identifier="local-candidate/vkusvill",
        trust_level="community",
        files={
            str(path.relative_to(source)): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file()
        },
    )
    installed = install_from_quarantine(quarantine, "vkusvill", "", bundle, scan, provenance)
    result["installed"] = str(installed)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

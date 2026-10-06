import copy

import pytest

from e2e.release import revision_of, run_gate, tree_digest, verify_identity


def identity():
    return {
        "version": "0.2.0",
        "origin": {"vcs_info": {"commit_id": "a" * 40}},
        "files": {"cli.py": "expected-content-hash"},
    }


def test_installed_identity():
    probe = identity()
    verify_identity(probe, "a" * 40, "0.2.0", probe["files"])


@pytest.mark.parametrize("change", ["version", "commit", "file", "missing", "extra"])
def test_gate_rejects_wrong_release_even_with_successful_doctor(change):
    probe = identity()
    expected_files = copy.deepcopy(probe["files"])
    if change == "version":
        probe["version"] = "0.1.0"
    elif change == "commit":
        probe["origin"]["vcs_info"]["commit_id"] = "b" * 40
    elif change == "file":
        probe["files"]["cli.py"] = "stale-cli"
    elif change == "missing":
        probe["files"] = {}
    else:
        probe["files"]["unexpected.py"] = "extra-code"
    with pytest.raises(AssertionError):
        verify_identity(probe, "a" * 40, "0.2.0", expected_files)


def test_digest_includes_nested_code_and_schemas_not_cache(tmp_path):
    (tmp_path / "cli.py").write_text("original")
    (tmp_path / "schemas.json").write_text("{}")
    (tmp_path / "submodule").mkdir()
    (tmp_path / "submodule/code.py").write_text("nested")
    before = tree_digest(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/cache.py").write_text("ignored")
    assert tree_digest(tmp_path) == before
    (tmp_path / "schemas.json").write_text('{"changed": true}')
    assert tree_digest(tmp_path) != before
    assert "submodule/code.py" in before


@pytest.mark.parametrize("pin", ["main", "a" * 39, "z" * 40])
def test_mutable_or_invalid_pin_rejected(tmp_path, pin):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/runtime.py").write_text(f"REVISION = {pin!r}\n")
    with pytest.raises(ValueError):
        revision_of(tmp_path)


def test_gate_refuses_personal_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "personal"))
    with pytest.raises(AssertionError, match="Disposable"):
        run_gate(tmp_path / "results")
    assert not (tmp_path / "results").exists()

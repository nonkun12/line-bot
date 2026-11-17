from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.rea_committed_diff_scanner import DiffScanBlocked, scan_committed_diff


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def fixture_repo(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "REA tests")
    git(root, "config", "user.email", "rea@example.invalid")
    (root / "scripts").mkdir()
    (root / "scripts" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(root, "add", "--all")
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    base = git(root, "rev-parse", "HEAD")
    return root, base


def commit(root: Path, message: str) -> str:
    git(root, "add", "--all")
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD")


def test_clean_committed_diff_is_sha_bound_and_read_only(tmp_path):
    root, base = fixture_repo(tmp_path)
    (root / "scripts" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    produced = commit(root, "safe change")
    before = git(root, "status", "--porcelain")
    result = scan_committed_diff(str(root), base_sha=base, produced_sha=produced,
                                 allowed_paths=["scripts/app.py"])
    assert result["status"] == "PASS"
    assert result["base_sha"] == base and result["produced_sha"] == produced
    assert len(result["diff_sha256"]) == 64
    assert result["changed_paths"] == ["scripts/app.py"]
    assert result["execution_authorized"] is False
    assert result["publish_authorized"] is False
    assert git(root, "status", "--porcelain") == before


def test_blocks_added_dangerous_flags_and_secret_patterns(tmp_path):
    root, base = fixture_repo(tmp_path)
    (root / "scripts" / "app.py").write_text(
        "VALUE = 2\n# AUTO_DEPLOY: true\nTOKEN = 'ghp_" + "A" * 40 + "'\n",
        encoding="utf-8",
    )
    produced = commit(root, "unsafe change")
    result = scan_committed_diff(str(root), base_sha=base, produced_sha=produced,
                                 allowed_paths=["scripts/app.py"])
    assert result["status"] == "BLOCKED"
    assert result["findings"][0]["severity"] == "CRITICAL"


def test_blocks_removed_guard_and_test_assertions(tmp_path):
    root, base = fixture_repo(tmp_path)
    path = root / "tests" / "test_guard.py"
    path.parent.mkdir()
    path.write_text("def test_guard():\n    assert True\n", encoding="utf-8")
    base = commit(root, "add guard test")
    path.write_text("def helper():\n    return True\n", encoding="utf-8")
    produced = commit(root, "remove test")
    result = scan_committed_diff(str(root), base_sha=base, produced_sha=produced,
                                 allowed_paths=["tests/test_guard.py"])
    assert result["status"] == "BLOCKED"
    assert {item["code"] for item in result["findings"]} == {"regression_test_removed_or_weakened"}


def test_blocks_out_of_scope_and_invalid_refs(tmp_path):
    root, base = fixture_repo(tmp_path)
    (root / "scripts" / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
    produced = commit(root, "change")
    with pytest.raises(DiffScanBlocked, match="changed_path_outside"):
        scan_committed_diff(str(root), base_sha=base, produced_sha=produced,
                            allowed_paths=["tests/test_other.py"])
    with pytest.raises(DiffScanBlocked, match="commit_sha_invalid"):
        scan_committed_diff(str(root), base_sha="bad", produced_sha=produced,
                            allowed_paths=["scripts/app.py"])

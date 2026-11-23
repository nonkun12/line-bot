from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import loop_rea_runner as rea


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "rea@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "REA"], check=True)
    test_file = root / "tests" / "test_example.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_original():\n    assert 1 == 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tests/test_example.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return root, test_file, base


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_pre_repair_rea_runs_scanner_and_tests_in_separate_processes(tmp_path):
    root, _test_file, base = _repo(tmp_path)
    result = rea.run_pre_repair_rea(root, base_sha=base)
    assert result["status"] == "PASS"
    assert result["stage"] == "PRE_REPAIR"
    assert result["independent"] is True
    assert result["base_sha"] == base
    assert result["evaluated_paths"] == []
    assert result["tests"]["status"] == "PASS"


def test_post_repair_rea_scans_exact_paths_without_changing_head_or_index(tmp_path):
    root, test_file, base = _repo(tmp_path)
    test_file.write_text(
        "def test_original():\n    assert 1 == 1\n\n"
        "def test_added_regression():\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    head_before = _git(root, "rev-parse", "HEAD")
    index_before = _git(root, "diff", "--cached", "--name-only")
    runner = rea.create_post_repair_rea_runner(root)
    result = runner({
        "stage": "POST_REPAIR",
        "base_sha": base,
        "allowed_paths": ["tests/test_example.py"],
        "changed_paths": ["tests/test_example.py"],
    })
    assert result["status"] == "PASS"
    assert result["independent"] is True
    assert result["base_sha"] == base
    assert result["evaluated_paths"] == ["tests/test_example.py"]
    assert len(result["diff_sha256"]) == 64
    assert _git(root, "rev-parse", "HEAD") == head_before
    assert _git(root, "diff", "--cached", "--name-only") == index_before
    assert _git(root, "status", "--porcelain", "--untracked-files=all") == "M tests/test_example.py"


def test_post_repair_rea_blocks_paths_outside_allowlist(tmp_path):
    root, test_file, base = _repo(tmp_path)
    test_file.write_text("def test_original():\n    assert 2 == 2\n", encoding="utf-8")
    runner = rea.create_post_repair_rea_runner(root)
    result = runner({
        "stage": "POST_REPAIR",
        "base_sha": base,
        "allowed_paths": ["tests/test_example.py"],
        "changed_paths": ["tests/test_example.py", "app.py"],
    })
    assert result["status"] == "BLOCKED"
    assert result["independent"] is False

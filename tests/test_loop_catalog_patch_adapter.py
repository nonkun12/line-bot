from __future__ import annotations

import hashlib
import subprocess

from scripts.loop_catalog_patch_adapter import create_catalog_patch_adapter


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    target = root / "tests" / "test_example.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tests/test_example.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return root, target, base


def _patch():
    return (
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1 +1,2 @@\n"
        "-value = 1\n"
        "+value = 1\n"
        "+assert value == 1\n"
    )


def _request(base):
    return {
        "base_sha": base,
        "allowed_paths": ["tests/test_example.py"],
        "provider_policy": "provider_free_only",
    }


def test_catalog_patch_applies_exact_preapproved_diff(tmp_path):
    root, target, base = _repo(tmp_path)
    patch = _patch()
    adapter = create_catalog_patch_adapter(
        root, patch, hashlib.sha256(patch.encode()).hexdigest()
    )
    result = adapter(_request(base))
    assert result["status"] == "PASS"
    assert result["provider"] == "preapproved_deterministic_catalog_patch"
    assert result["changed_paths"] == ["tests/test_example.py"]
    assert "assert value == 1" in target.read_text(encoding="utf-8")


def test_catalog_patch_rejects_hash_mismatch_without_mutation(tmp_path):
    root, target, base = _repo(tmp_path)
    patch = _patch()
    adapter = create_catalog_patch_adapter(root, patch, "0" * 64)
    result = adapter(_request(base))
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "catalog_patch_hash_mismatch"
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_catalog_patch_rejects_out_of_allowlist_paths(tmp_path):
    root, target, base = _repo(tmp_path)
    patch = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -0,0 +1 @@\n"
        "+unsafe = True\n"
    )
    adapter = create_catalog_patch_adapter(
        root, patch, hashlib.sha256(patch.encode()).hexdigest()
    )
    result = adapter(_request(base))
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "catalog_patch_paths_outside_allowlist"
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_catalog_patch_rejects_git_metadata_and_file_creation(tmp_path):
    root, target, base = _repo(tmp_path)
    patch = (
        "--- a/app.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-unsafe = True\n"
    )
    adapter = create_catalog_patch_adapter(
        root, patch, hashlib.sha256(patch.encode()).hexdigest()
    )
    result = adapter(_request(base))
    assert result["status"] == "BLOCKED"
    assert target.read_text(encoding="utf-8") == "value = 1\n"

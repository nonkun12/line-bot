from pathlib import Path
import subprocess

from core.execution_safety import GitWorktreeSafetyGate


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(("git", "-C", str(root), *args), text=True).strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "allowed.txt").write_text("base\n")
    (root / "other.txt").write_text("base\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD")


def test_gate_accepts_only_changes_inside_manifest(tmp_path):
    root, baseline = _repo(tmp_path)
    (root / "allowed.txt").write_text("changed\n")
    result = type("R", (), {"success": True})()
    gate = GitWorktreeSafetyGate(root, baseline, ("allowed.txt",))
    assert gate.verify(None, result, ("allowed.txt",)) is True


def test_gate_rejects_out_of_scope_changes(tmp_path):
    root, baseline = _repo(tmp_path)
    (root / "other.txt").write_text("changed\n")
    result = type("R", (), {"success": True})()
    gate = GitWorktreeSafetyGate(root, baseline, ("allowed.txt",))
    assert gate.verify(None, result, ("allowed.txt",)) is False


def test_gate_rejects_when_baseline_is_not_ancestor(tmp_path):
    root, baseline = _repo(tmp_path)
    _git(root, "checkout", "--orphan", "other")
    (root / "other.txt").write_text("other\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "other")
    result = type("R", (), {"success": True})()
    gate = GitWorktreeSafetyGate(root, baseline, ("allowed.txt",))
    assert gate.verify(None, result, ("allowed.txt",)) is False


def test_gate_rejects_unsafe_manifest_paths(tmp_path):
    root, baseline = _repo(tmp_path)
    (root / "allowed.txt").write_text("changed\n")
    result = type("R", (), {"success": True, "changed_resources": frozenset({"allowed.txt"})})()
    gate = GitWorktreeSafetyGate(root, baseline, ("../allowed.txt",))
    assert gate.verify(None, result, ("../allowed.txt",)) is False


def test_gate_rejects_symlink_escape(tmp_path):
    root, baseline = _repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n")
    link = root / "allowed.txt"
    link.unlink()
    link.symlink_to(outside)
    result = type("R", (), {"success": True, "changed_resources": frozenset({"allowed.txt"})})()
    gate = GitWorktreeSafetyGate(root, baseline, ("allowed.txt",))
    assert gate.verify(None, result, ("allowed.txt",)) is False


def test_gate_allows_verified_noop(tmp_path):
    root, baseline = _repo(tmp_path)
    result = type("R", (), {"success": True, "changed_resources": frozenset()})()
    gate = GitWorktreeSafetyGate(root, baseline, ("allowed.txt",))
    assert gate.verify(None, result, ("allowed.txt",)) is True


def test_gate_rejects_protected_directory_manifest(tmp_path):
    root, baseline = _repo(tmp_path)
    (root / "allowed.txt").write_text("changed\n")
    result = type("R", (), {"success": True, "changed_resources": frozenset({"allowed.txt"})})()
    gate = GitWorktreeSafetyGate(root, baseline, (".github/",))
    assert gate.verify(None, result, (".github/",)) is False


def test_gate_rejects_protected_ancestor_manifest(tmp_path):
    root, baseline = _repo(tmp_path)
    (root / "allowed.txt").write_text("changed\n")
    result = type("R", (), {"success": True, "changed_resources": frozenset({"allowed.txt"})})()
    gate = GitWorktreeSafetyGate(root, baseline, ("core",))
    assert gate.verify(None, result, ("core",)) is False


def test_gate_rejects_rename_of_protected_file(tmp_path):
    root, baseline = _repo(tmp_path)
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    protected = workflow / "ci.yml"
    protected.write_text("name: ci\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "add workflow")
    baseline = _git(root, "rev-parse", "HEAD")
    target = root / "docs-ci.yml"
    protected.rename(target)
    result = type("R", (), {"success": True, "changed_resources": frozenset({"docs-ci.yml"})})()
    gate = GitWorktreeSafetyGate(root, baseline, ("docs-ci.yml",))
    assert gate.verify(None, result, ("docs-ci.yml",)) is False

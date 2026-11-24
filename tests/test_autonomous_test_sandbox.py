from __future__ import annotations

import subprocess

from scripts import autonomous_test_sandbox as sandbox


def test_sandbox_blocks_when_bubblewrap_is_unavailable(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_stocks.py"
    target.parent.mkdir()
    target.write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)

    result = sandbox.run_pytest_sandboxed(
        ["python", "-m", "pytest", "tests/test_stocks.py"],
        repo_root=tmp_path, test_paths=["tests/test_stocks.py"], timeout=10,
    )

    assert result.returncode != 0
    assert "bubblewrap_unavailable" in result.stderr


def test_sandbox_rejects_multiple_or_unallowlisted_test_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/bwrap")
    result = sandbox.run_pytest_sandboxed(
        ["python", "-m", "pytest"], repo_root=tmp_path,
        test_paths=["tests/test_stocks.py", "tests/test_other.py"], timeout=10,
    )
    assert result.returncode != 0
    assert "exactly_one_allowlisted_test_file_required" in result.stderr


def test_sandbox_uses_network_namespace_and_read_only_repository(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_stocks.py"
    target.parent.mkdir()
    target.write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(
        sandbox.shutil, "which",
        lambda name: { "bwrap": "/usr/bin/bwrap", "prlimit": "/usr/bin/prlimit" }.get(name),
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    result = sandbox.run_pytest_sandboxed(
        ["/usr/bin/python3", "-m", "pytest", "-p", "no:cacheprovider", "tests/test_stocks.py"],
        repo_root=tmp_path, test_paths=["tests/test_stocks.py"], timeout=10,
    )
    assert result.returncode == 0
    command = captured["command"]
    assert command[0] == "/usr/bin/prlimit"
    assert "--nproc=64" in command
    assert "--unshare-all" in command
    assert "--ro-bind" in command
    assert "--tmpfs" in command
    assert "--bind" in command
    assert "--clearenv" in command
    assert captured["kwargs"]["timeout"] == 10
    assert captured["kwargs"]["env"] == {"PATH": sandbox.os.environ.get("PATH", sandbox.os.defpath)}


def test_sandbox_blocks_when_process_limit_tool_is_unavailable(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_stocks.py"
    target.parent.mkdir()
    target.write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(
        sandbox.shutil, "which",
        lambda name: "/usr/bin/bwrap" if name == "bwrap" else None,
    )

    result = sandbox.run_pytest_sandboxed(
        ["python", "-m", "pytest", "tests/test_stocks.py"],
        repo_root=tmp_path, test_paths=["tests/test_stocks.py"], timeout=10,
    )

    assert result.returncode != 0
    assert "prlimit_unavailable" in result.stderr

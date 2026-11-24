from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from scripts.autonomous_test_sandbox import (
    SandboxError,
    build_sandbox_command,
    run_sandboxed_pytest,
)


def test_command_uses_empty_root_and_never_mounts_host_root_or_target_writable(tmp_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    target = root / "tests" / "test_one.py"
    target.write_text("def test_ok(): pass\n", encoding="utf-8")

    command = build_sandbox_command(root, "tests/test_one.py")
    joined = " ".join(command)

    assert "--tmpfs /" in joined
    assert "--clearenv" in command
    assert "--unshare-all" in command
    assert "--ro-bind / /" not in joined
    assert "--bind" not in command
    assert str(root) in command
    assert str(Path(sys.prefix).resolve()) in command
    library_dir = sysconfig.get_config_var("LIBDIR")
    if library_dir:
        assert str(Path(library_dir).resolve()) in command
        assert "--setenv" in command
        assert "LD_LIBRARY_PATH" in command
    assert "tests/test_one.py" in command


@pytest.mark.parametrize("bad_path", [
    "../outside.py",
    "tests/../outside.py",
    "/tmp/test.py",
    "tests\\test.py",
    "src/test_not_allowed.py",
])
def test_rejects_non_allowlisted_paths(tmp_path, bad_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    with pytest.raises(SandboxError):
        build_sandbox_command(root, bad_path)


def test_rejects_symlinked_test_target(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside.py"
    (root / "tests").mkdir(parents=True)
    outside.write_text("def test_ok(): pass\n", encoding="utf-8")
    (root / "tests" / "test_link.py").symlink_to(outside)
    with pytest.raises(SandboxError, match="symlink"):
        build_sandbox_command(root, "tests/test_link.py")


@pytest.mark.skipif(
    not shutil.which("bwrap") or not shutil.which("prlimit"),
    reason="bubblewrap/prlimit unavailable outside the required CI sandbox job",
)
def test_real_sandbox_denies_host_writes_credentials_sockets_and_network(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    target = tests / "test_boundary.py"
    host_marker = root / "host-marker"
    secret_name = "SANDBOX_HOST_SECRET"
    monkeypatch.setenv(secret_name, "must-not-cross-boundary")

    target.write_text(
        "import os, socket\n"
        "from pathlib import Path\n"
        "def test_repository_and_test_file_are_read_only():\n"
        "    for p in (Path.cwd() / 'host-marker', Path(__file__)):\n"
        "        try: p.write_text('escape')\n"
        "        except OSError: pass\n"
        "        else: raise AssertionError('host path writable')\n"
        "def test_tmpfs_is_writable_and_home_is_isolated():\n"
        "    p = Path('/tmp/sandbox-write'); p.write_text('ok'); assert p.read_text() == 'ok'\n"
        "    assert os.environ.get('HOME') == '/tmp'\n"
        "    assert not os.environ.get('SANDBOX_HOST_SECRET')\n"
        "def test_host_runtime_sockets_are_not_visible():\n"
        "    assert not Path('/run/docker.sock').exists()\n"
        "    assert not Path('/var/run/docker.sock').exists()\n"
        "def test_network_namespace_is_isolated():\n"
        "    assert {name for _, name in socket.if_nameindex()} <= {'lo'}\n"
        "    s = socket.socket(); s.settimeout(1)\n"
        "    try:\n"
        "        try: s.connect(('1.1.1.1', 53))\n"
        "        except OSError: pass\n"
        "        else: raise AssertionError('outbound network available')\n"
        "    finally: s.close()\n",
        encoding="utf-8",
    )

    command = build_sandbox_command(root, "tests/test_boundary.py")
    # Probe the same namespace with its known-good shell before diagnosing an
    # interpreter ENOENT. This distinguishes a missing bind target from a
    # missing ELF loader without relaxing the production sandbox.
    bwrap_index = command.index(shutil.which("bwrap"))
    separator = command.index("--", bwrap_index + 1)
    probe = command[:separator + 1] + [
        "/bin/sh", "-c",
        "ls -ld /python-runtime /python-runtime/bin; "
        "ls -l /python-runtime/bin/python*; "
        "ls -l /lib64/ld-linux* /usr/lib/x86_64-linux-gnu/ld-linux* 2>/dev/null || true; "
        "test -x /python-runtime/bin/python3.13 && echo interpreter-executable || echo interpreter-missing",
    ]
    probe_result = subprocess.run(
        probe, cwd=root, text=True, capture_output=True, timeout=30,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    result = run_sandboxed_pytest(root, "tests/test_boundary.py", timeout=120)
    assert result.returncode == 0, (
        result.stdout + result.stderr
        + "\\nprobe_stdout=" + probe_result.stdout
        + "\\nprobe_stderr=" + probe_result.stderr
        + "\\npython=" + repr(sys.executable)
        + " prefix=" + repr(sys.prefix)
        + " resolved=" + repr(str(Path(sys.executable).resolve()))
        + "\\ncommand=" + repr(command)
    )
    assert not host_marker.exists()
    assert "must-not-cross-boundary" not in result.stdout + result.stderr


def test_missing_sandbox_runtime_fails_closed(tmp_path, monkeypatch):
    from scripts import autonomous_test_sandbox as sandbox

    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(SandboxError, match="runtime_unavailable"):
        build_sandbox_command(root, "tests/test_x.py")

"""Execute generated regression tests under a fail-closed network seccomp filter.

This helper is intended to run only inside the read-only Bubblewrap sandbox
assembled by line_development_worker_v2.py. It installs a Linux seccomp filter
before exec'ing pytest; the filter denies network-related syscalls.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import sys

_NETWORK_SYSCALLS = (
    "socket", "socketpair", "connect", "accept", "accept4",
    "sendto", "sendmsg", "sendmmsg", "recvfrom", "recvmsg", "recvmmsg",
    "bind", "listen", "getsockname", "getpeername", "setsockopt",
    "getsockopt", "shutdown", "io_uring_setup", "io_uring_enter",
    "io_uring_register",
)
_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000 | errno.EPERM
_PR_SET_NO_NEW_PRIVS = 38


def install_network_deny_filter() -> None:
    """Install a seccomp allow-by-default filter denying network syscalls."""
    library_name = ctypes.util.find_library("seccomp")
    if not library_name:
        raise RuntimeError("seccomp_library_unavailable")
    lib = ctypes.CDLL(library_name, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint,
    ]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None

    context = lib.seccomp_init(_SCMP_ACT_ALLOW)
    if not context:
        raise RuntimeError("seccomp_init_failed")
    try:
        resolved: set[str] = set()
        for name in _NETWORK_SYSCALLS:
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0:
                continue
            result = lib.seccomp_rule_add(context, _SCMP_ACT_ERRNO, number, 0)
            if result != 0:
                raise RuntimeError("seccomp_rule_add_failed")
            resolved.add(name)
        if not {"socket", "connect"}.issubset(resolved):
            raise RuntimeError("required_network_syscalls_unavailable")
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [
            ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_ulong, ctypes.c_ulong,
        ]
        libc.prctl.restype = ctypes.c_int
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise RuntimeError("no_new_privileges_failed")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_load_failed")
    finally:
        lib.seccomp_release(context)


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("AUTO_TEST_SANDBOX_BLOCKED: linux_required")
        return 2
    if os.environ.get("AUTONOMOUS_TEST_SANDBOX") != "1":
        print("AUTO_TEST_SANDBOX_BLOCKED: sandbox_marker_missing")
        return 2
    if len(sys.argv) < 3 or sys.argv[1] != "--":
        print("AUTO_TEST_SANDBOX_BLOCKED: command_required")
        return 2
    command = sys.argv[2:]
    if not command or not os.path.isabs(command[0]):
        print("AUTO_TEST_SANDBOX_BLOCKED: absolute_executable_required")
        return 2
    try:
        install_network_deny_filter()
    except (OSError, RuntimeError, AttributeError):
        print("AUTO_TEST_SANDBOX_BLOCKED: seccomp_setup_failed")
        return 2
    os.execv(command[0], command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

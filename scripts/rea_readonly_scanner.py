"""Read-only, deterministic REA scanner for repository evidence.

The scanner never edits files, executes project code, runs tests, or contacts
external services. It emits metadata-only findings; source snippets and secret
values are never copied into the report.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ALLOWED_ROOTS = (".github/workflows/", "core/", "scripts/", "tests/", "docs/rea/")
ALLOWED_SUFFIXES = frozenset({".py", ".json", ".yml", ".yaml", ".md"})
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 5000
DANGEROUS_FLAG_RE = re.compile(
    r"""^[ \t]*(AUTO_APPLY_PATCH|AUTO_DEPLOY)[ \t]*[:=][ \t]*["\']?(true|yes|1)["\']?[ \t]*(?:#.*)?$""",
    re.IGNORECASE | re.MULTILINE,
)


class ScanBlocked(RuntimeError):
    """Raised when the scanner cannot establish a complete, safe input set."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        # Never echo Git stderr; it can contain paths or environment details.
        raise ScanBlocked("git_evidence_unavailable")
    return result.stdout


def _finding(
    *, category: str, severity: str, confidence: str, target_sha: str,
    path: str, line: int | None, evidence_code: str, hypothesis: str,
    suggested_fix: str, required_tests: list[str],
) -> dict[str, Any]:
    identity = "|".join((target_sha, category, path, str(line or 0), evidence_code))
    return {
        "finding_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "target_sha": target_sha,
        "evidence": {
            "path": path,
            "line": line,
            "check": evidence_code,
        },
        "root_cause_hypothesis": hypothesis,
        "suggested_fix": suggested_fix,
        "required_tests": required_tests,
        "status": "REVIEW_REQUIRED",
    }


def scan_repository(repo_root: str | Path) -> dict[str, Any]:
    """Scan a bounded allowlist and return a stable, metadata-only report."""
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ScanBlocked("repository_root_unavailable")

    target_sha = _git(root, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", target_sha):
        raise ScanBlocked("target_sha_invalid")

    # A HEAD hash is meaningful evidence only if tracked inputs match that HEAD.
    # Also reject untracked files so an incomplete checkout cannot look clean.
    if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise ScanBlocked("working_tree_not_clean")

    # The -v index listing exposes assume-unchanged (lowercase tags) and
    # skip-worktree (S) flags. Either can conceal worktree changes from status.
    index_flags = _git(root, "ls-files", "-v", "-z", "--")
    for record in index_flags.split("\0"):
        if not record:
            continue
        if len(record) < 3 or record[1] != " ":
            raise ScanBlocked("git_index_flag_entry_invalid")
        tag = record[0]
        if tag.islower() or tag == "S":
            raise ScanBlocked("git_index_flags_unsafe")

    # -z preserves filenames without Git's quoted-path display format.
    entries = _git(root, "ls-files", "-s", "-z", "--").split("\0")
    candidates: list[tuple[str, str]] = []
    for entry in entries:
        if not entry:
            continue
        if "\t" not in entry:
            raise ScanBlocked("git_index_entry_invalid")
        metadata, path = entry.split("\t", 1)
        parts = metadata.split()
        if len(parts) < 3:
            raise ScanBlocked("git_index_entry_invalid")
        mode = parts[0]
        # Skip symlinks, submodules, and paths outside the explicit allowlist.
        if mode != "100644" and mode != "100755":
            continue
        if not path.startswith(ALLOWED_ROOTS):
            continue
        if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        candidates.append((path, parts[2]))

    if len(candidates) > MAX_FILES:
        raise ScanBlocked("scan_file_limit_exceeded")

    findings: list[dict[str, Any]] = []
    scanned = 0
    skipped_large = 0
    for relative, _blob_sha in sorted(candidates):
        path = root / relative
        # Resolve and verify again to reject traversal and symlink tricks.
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ScanBlocked("tracked_path_boundary_violation")
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped_large += 1
                continue
            raw = path.read_bytes()
            source = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            raise ScanBlocked("tracked_file_read_incomplete") from None

        scanned += 1
        suffix = path.suffix.lower()
        if suffix == ".py":
            try:
                ast.parse(source, filename=relative)
            except (SyntaxError, ValueError, TypeError) as exc:
                line = getattr(exc, "lineno", None)
                findings.append(_finding(
                    category="python_syntax",
                    severity="HIGH",
                    confidence="HIGH",
                    target_sha=target_sha,
                    path=relative,
                    line=line if isinstance(line, int) else None,
                    evidence_code="ast_parse_failed",
                    hypothesis="The tracked Python file may not be syntactically valid.",
                    suggested_fix="Review the reported line and add or run a focused syntax regression test.",
                    required_tests=["python -m py_compile <reviewed-file>"],
                ))
        elif suffix == ".json":
            try:
                json.loads(source)
            except (json.JSONDecodeError, ValueError):
                findings.append(_finding(
                    category="json_syntax",
                    severity="HIGH",
                    confidence="HIGH",
                    target_sha=target_sha,
                    path=relative,
                    line=None,
                    evidence_code="json_parse_failed",
                    hypothesis="The tracked JSON file may be malformed.",
                    suggested_fix="Validate the JSON structure against its intended schema.",
                    required_tests=["python -m json.tool <reviewed-file>"],
                ))

        if relative.startswith(".github/workflows/"):
            for match in DANGEROUS_FLAG_RE.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                flag_name = match.group(1).upper()
                findings.append(_finding(
                    category="safety_flag",
                    severity="CRITICAL",
                    confidence="MEDIUM",
                    target_sha=target_sha,
                    path=relative,
                    line=line,
                    evidence_code=f"{flag_name.lower()}_enabled_literal",
                    hypothesis=f"{flag_name} appears explicitly enabled in a workflow file.",
                    suggested_fix=f"Restore {flag_name}=false and verify all downstream guards.",
                    required_tests=["Review the workflow expression and its fail-closed tests."],
                ))

    findings.sort(key=lambda item: (
        item["evidence"]["path"], item["evidence"]["line"] or 0,
        item["category"], item["finding_id"],
    ))
    status = "BLOCKED" if skipped_large else ("FINDINGS" if findings else "PASS")
    return {
        "schema_version": 1,
        "scanner": "rea-readonly-mvp",
        "status": status,
        "target_sha": target_sha,
        "complete": skipped_large == 0,
        "files_scanned": scanned,
        "files_skipped_oversize": skipped_large,
        "findings_count": len(findings),
        "findings": findings,
        "capabilities": {
            "read_only": True,
            "executes_project_code": False,
            "runs_tests": False,
            "network_access": False,
            "patches_tasks_hold_merge_deploy": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root to inspect")
    args = parser.parse_args(argv)
    try:
        report = scan_repository(args.repo_root)
    except Exception:
        print(json.dumps({
            "schema_version": 1,
            "scanner": "rea-readonly-mvp",
            "status": "BLOCKED",
            "complete": False,
            "reason_code": "scan_evidence_incomplete",
            "capabilities": {"read_only": True, "patches_tasks_hold_merge_deploy": False},
        }, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else (1 if report["status"] == "FINDINGS" else 2)


if __name__ == "__main__":
    raise SystemExit(main())

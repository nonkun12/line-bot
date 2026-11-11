"""Read-only, deterministic REA scanner for repository evidence.

The scanner never edits files, executes project code, runs tests, or contacts
external services. It emits metadata-only findings; source snippets and secret
values are never copied into the report. JavaScript and SQL checks are static
contract heuristics, not runtime or database-concurrency verification.
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

ALLOWED_ROOTS = (
    ".github/workflows/", "core/", "scripts/", "tests/", "docs/rea/",
    "routes/", "static/", "templates/", "apps/", "cloudflare/",
)
ALLOWED_ROOT_FILES = frozenset({"config.py"})
ALLOWED_SUFFIXES = frozenset({
    ".py", ".json", ".yml", ".yaml", ".md", ".js", ".html", ".sql",
})
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 5000
WORKFLOW_WRITE_ALL_RE = re.compile(
    r"""^[ \t]*permissions[ \t]*:[ \t]*write-all[ \t]*(?:#.*)?$""",
    re.IGNORECASE | re.MULTILINE,
)
DANGEROUS_FLAG_RE = re.compile(
    r"""^[ \t]*(AUTO_APPLY_PATCH|AUTO_DEPLOY)[ \t]*[:=][ \t]*["\']?(true|yes|1)["\']?[ \t]*(?:#.*)?$""",
    re.IGNORECASE | re.MULTILINE,
)
ORCA_WORKER_PATH = "cloudflare/orca-test-api/src/index.js"
ORCA_WORKER_CONTRACTS = {
    "constant_time_auth": (r"function\s+safeEqual\b", "HIGH"),
    "api_token_auth": (r"async\s+function\s+authorized\b", "HIGH"),
    "atomic_d1_batch": (r"env\.DB\.batch\s*\(", "HIGH"),
    "append_only_nonce_ledger": (r"task_approval_nonces", "CRITICAL"),
    "owner_scoped_status": (r"x-orca-task-owner", "HIGH"),
    "lease_token_completion": (r"claim_token", "HIGH"),
    "notification_outbox": (r"notification_outbox", "HIGH"),
    "hmac_signature": (r"crypto\.subtle\.(?:importKey|sign)", "HIGH"),
}


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
        "evidence": {"path": path, "line": line, "check": evidence_code},
        "root_cause_hypothesis": hypothesis,
        "suggested_fix": suggested_fix,
        "required_tests": required_tests,
        "status": "REVIEW_REQUIRED",
    }


def _add_contract_finding(
    findings: list[dict[str, Any]], *, target_sha: str, path: str,
    source: str, category: str, severity: str, evidence_code: str,
    hypothesis: str, suggested_fix: str, required_test: str,
) -> None:
    findings.append(_finding(
        category=category, severity=severity, confidence="MEDIUM",
        target_sha=target_sha, path=path, line=None,
        evidence_code=evidence_code, hypothesis=hypothesis,
        suggested_fix=suggested_fix, required_tests=[required_test],
    ))


def _scan_worker_contract(
    source: str, relative: str, target_sha: str,
    findings: list[dict[str, Any]],
) -> None:
    for contract, (pattern, severity) in ORCA_WORKER_CONTRACTS.items():
        if not re.search(pattern, source, re.IGNORECASE):
            _add_contract_finding(
                findings, target_sha=target_sha, path=relative, source=source,
                category="cloudflare_worker_contract", severity=severity,
                evidence_code=f"missing_{contract}",
                hypothesis=f"The ORCA Worker source does not visibly satisfy the {contract} static contract.",
                suggested_fix="Review the endpoint implementation and restore the missing fail-closed security contract.",
                required_test="Add a focused Worker contract regression test and verify it against the deployed Workers runtime.",
            )


def _scan_sql_contract(
    source: str, relative: str, target_sha: str,
    findings: list[dict[str, Any]],
) -> None:
    lowered = source.lower()
    if "create table" not in lowered:
        return
    if "task_approval_nonces" in lowered:
        checks = {
            "nonce_primary_key": r"approval_nonce\s+text\s+primary\s+key",
            "approval_id_unique": r"approval_id\s+text\s+not\s+null\s+unique",
            "task_foreign_key": r"foreign\s+key\s*\(\s*task_id\s*\)\s*references\s+tasks\s*\(\s*task_id\s*\)",
        }
        for contract, pattern in checks.items():
            if not re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
                _add_contract_finding(
                    findings, target_sha=target_sha, path=relative, source=source,
                    category="d1_migration_contract", severity="CRITICAL",
                    evidence_code=f"missing_{contract}",
                    hypothesis=f"The append-only approval nonce table may not enforce {contract}.",
                    suggested_fix="Review the D1 schema and enforce replay-resistant uniqueness and task referential integrity.",
                    required_test="Apply the migration to an isolated SQLite/D1-compatible fixture and test duplicate nonce and approval IDs.",
                )
    if "notification_outbox" in lowered and "create table" in lowered:
        if not re.search(r"outbox_id\s+text\s+primary\s+key", lowered):
            _add_contract_finding(
                findings, target_sha=target_sha, path=relative, source=source,
                category="d1_migration_contract", severity="HIGH",
                evidence_code="missing_outbox_primary_key",
                hypothesis="The notification outbox may not have a stable unique row identity.",
                suggested_fix="Give every outbox record a primary key and verify idempotent insertion.",
                required_test="Test duplicate outbox IDs and concurrent completion transactions.",
            )


def scan_repository(repo_root: str | Path) -> dict[str, Any]:
    """Scan the explicit repository allowlist and return a stable metadata-only report."""
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ScanBlocked("repository_root_unavailable")

    target_sha = _git(root, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", target_sha):
        raise ScanBlocked("target_sha_invalid")
    if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise ScanBlocked("working_tree_not_clean")

    index_flags = _git(root, "ls-files", "-v", "-z", "--")
    for record in index_flags.split("\0"):
        if not record:
            continue
        if len(record) < 3 or record[1] != " ":
            raise ScanBlocked("git_index_flag_entry_invalid")
        if record[0].islower() or record[0] == "S":
            raise ScanBlocked("git_index_flags_unsafe")

    entries = _git(root, "ls-files", "-s", "-z", "--").split("\0")
    candidates: list[tuple[str, str]] = []
    skipped_unsupported = 0
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
        in_scope = (
            path.startswith(ALLOWED_ROOTS) or path in ALLOWED_ROOT_FILES
        ) and Path(path).suffix.lower() in ALLOWED_SUFFIXES
        if mode not in {"100644", "100755"}:
            if in_scope:
                skipped_unsupported += 1
            continue
        if not (path.startswith(ALLOWED_ROOTS) or path in ALLOWED_ROOT_FILES):
            continue
        if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        candidates.append((path, parts[2]))

    if len(candidates) > MAX_FILES:
        raise ScanBlocked("scan_file_limit_exceeded")

    findings: list[dict[str, Any]] = []
    scanned = 0
    skipped_large = 0
    evidence_rows: list[str] = []
    for relative, blob_sha in sorted(candidates):
        path = root / relative
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ScanBlocked("tracked_path_boundary_violation")
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped_large += 1
                continue
            raw = path.read_bytes()
            source = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            raise ScanBlocked("tracked_file_read_incomplete") from None

        scanned += 1
        evidence_rows.append(f"{relative}\0{blob_sha}\0{hashlib.sha256(raw).hexdigest()}")
        suffix = path.suffix.lower()
        if suffix == ".py":
            try:
                ast.parse(source, filename=relative)
            except (SyntaxError, ValueError, TypeError) as exc:
                line = getattr(exc, "lineno", None)
                findings.append(_finding(
                    category="python_syntax", severity="HIGH", confidence="HIGH",
                    target_sha=target_sha, path=relative,
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
                    category="json_syntax", severity="HIGH", confidence="HIGH",
                    target_sha=target_sha, path=relative, line=None,
                    evidence_code="json_parse_failed",
                    hypothesis="The tracked JSON file may be malformed.",
                    suggested_fix="Validate the JSON structure against its intended schema.",
                    required_tests=["python -m json.tool <reviewed-file>"],
                ))

        if relative.startswith(".github/workflows/"):
            for match in WORKFLOW_WRITE_ALL_RE.finditer(source):
                findings.append(_finding(
                    category="workflow_permission", severity="HIGH", confidence="HIGH",
                    target_sha=target_sha, path=relative,
                    line=source.count("\n", 0, match.start()) + 1,
                    evidence_code="workflow_write_all_permissions",
                    hypothesis="The workflow grants every available GitHub Actions permission instead of using least privilege.",
                    suggested_fix="Replace write-all with the minimum explicit permissions required by each job.",
                    required_tests=["Review job-level permissions and add a least-privilege regression test."],
                ))
            for match in DANGEROUS_FLAG_RE.finditer(source):
                flag_name = match.group(1).upper()
                findings.append(_finding(
                    category="safety_flag", severity="CRITICAL", confidence="MEDIUM",
                    target_sha=target_sha, path=relative,
                    line=source.count("\n", 0, match.start()) + 1,
                    evidence_code=f"{flag_name.lower()}_enabled_literal",
                    hypothesis=f"{flag_name} appears explicitly enabled in a workflow file.",
                    suggested_fix=f"Restore {flag_name}=false and verify all downstream guards.",
                    required_tests=["Review the workflow expression and its fail-closed tests."],
                ))

        if relative == ORCA_WORKER_PATH:
            _scan_worker_contract(source, relative, target_sha, findings)
        if suffix == ".sql":
            _scan_sql_contract(source, relative, target_sha, findings)
        if relative == "config.py" and "_get_orca_task_status" in source:
            if "X-ORCA-Task-Owner" not in source:
                _add_contract_finding(
                    findings, target_sha=target_sha, path=relative, source=source,
                    category="line_identity_contract", severity="HIGH",
                    evidence_code="missing_owner_header",
                    hypothesis="The LINE task status client may not bind status lookup to the verified LINE submitter.",
                    suggested_fix="Send the verified LINE user ID in the X-ORCA-Task-Owner header, not URL query parameters.",
                    required_test="Test that status lookup sends the owner header and no user_id query parameter.",
                )

    findings.sort(key=lambda item: (
        item["evidence"]["path"], item["evidence"]["line"] or 0,
        item["category"], item["finding_id"],
    ))
    coverage_complete = skipped_large == 0 and skipped_unsupported == 0
    status = "BLOCKED" if not coverage_complete else ("FINDINGS" if findings else "PASS")
    evidence_material = "\n".join([target_sha, *evidence_rows]).encode("utf-8")
    return {
        "schema_version": 2,
        "scanner": "rea-readonly-mvp",
        "status": status,
        "target_sha": target_sha,
        "complete": coverage_complete,
        "coverage": "COMPLETE" if coverage_complete else "INCOMPLETE",
        "scope": {
            "full_repository": False,
            "roots": list(ALLOWED_ROOTS),
            "root_files": sorted(ALLOWED_ROOT_FILES),
            "suffixes": sorted(ALLOWED_SUFFIXES),
            "note": "COMPLETE applies only to this explicit allowlist; excluded paths are not inspected.",
        },
        "evidence_sha256": hashlib.sha256(evidence_material).hexdigest(),
        "files_scanned": scanned,
        "files_skipped_oversize": skipped_large,
        "files_skipped_unsupported": skipped_unsupported,
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
    except ScanBlocked as exc:
        print(json.dumps({
            "schema_version": 2, "scanner": "rea-readonly-mvp",
            "status": "BLOCKED", "complete": False,
            "reason_code": str(exc),
            "capabilities": {"read_only": True, "patches_tasks_hold_merge_deploy": False},
        }, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({
            "schema_version": 2, "scanner": "rea-readonly-mvp",
            "status": "BLOCKED", "complete": False,
            "reason_code": "unexpected_scan_error",
            "capabilities": {"read_only": True, "patches_tasks_hold_merge_deploy": False},
        }, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else (1 if report["status"] == "FINDINGS" else 2)


if __name__ == "__main__":
    raise SystemExit(main())

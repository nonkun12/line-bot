"""Fail-closed REA preflight for development entrypoints."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.rea_control_tower_adapter import (
    prepare_rea_evidence,
    rea_evidence_is_valid_pass,
)

ROOT = Path(__file__).resolve().parents[1]
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def require_rea_pass(repo_root: str | Path = ROOT) -> dict[str, Any]:
    """Require complete, SHA-bound, schema-valid REA PASS evidence."""
    root = Path(repo_root).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
        expected_sha = result.stdout.strip() if result.returncode == 0 else ""
        if not _SHA_RE.fullmatch(expected_sha):
            raise ValueError("head_sha_unavailable")
        evidence = prepare_rea_evidence(root, expected_sha=expected_sha)
        if (
            not isinstance(evidence, dict)
            or evidence.get("gate") != "PASS"
            or not rea_evidence_is_valid_pass(evidence, expected_sha=expected_sha)
        ):
            reason = evidence.get("reason_code", "rea_pass_evidence_invalid") if isinstance(evidence, dict) else "rea_report_invalid"
            raise ValueError(str(reason)[:100])
        return evidence
    except Exception as exc:
        # Keep failure output deterministic and free of paths/secrets/provider details.
        reason = str(exc) if isinstance(exc, ValueError) else "rea_preflight_error"
        raise RuntimeError(f"REA_BLOCKED reason={reason[:100]}") from None


def main() -> int:
    try:
        evidence = require_rea_pass()
    except RuntimeError as exc:
        print(str(exc))
        return 80
    print(json.dumps({
        "gate": evidence["gate"],
        "target_sha": evidence["target_sha"],
        "scanner_status": evidence["scanner_status"],
        "finding_count": evidence["finding_count"],
        "blocking_count": evidence["blocking_count"],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

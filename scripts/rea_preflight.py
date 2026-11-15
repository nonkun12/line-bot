"""Fail-closed REA preflight for workflows that bypass the guarded runtime."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.rea_control_tower_adapter import prepare_rea_evidence


def evaluate_rea(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"gate": "BLOCKED", "reason_code": "rea_head_unavailable"}
    expected_sha = result.stdout.strip()
    if result.returncode != 0:
        return {"gate": "BLOCKED", "reason_code": "rea_head_unavailable"}
    return prepare_rea_evidence(root, expected_sha=expected_sha)


def require_rea_pass(repo_root: str | Path) -> dict[str, Any]:
    evidence = evaluate_rea(repo_root)
    print("REA_PREFLIGHT=" + json.dumps(evidence, ensure_ascii=False, sort_keys=True), flush=True)
    if evidence.get("gate") != "PASS":
        raise RuntimeError("REA preflight blocked; no app creation or publication is permitted")
    return evidence


def main() -> int:
    try:
        require_rea_pass(Path.cwd())
    except Exception:
        return 80
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

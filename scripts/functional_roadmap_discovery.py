"""Read-only discovery of explicit, unfinished product roadmap items.

Only unchecked bullets under the single, explicit README roadmap heading are
considered. Results are informational review candidates, never executable tasks.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_HEADING = "今後の実装予定"
_ITEM = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$")
_MAX_CANDIDATES = 20


def discover_roadmap_candidates(readme_path: Path) -> list[dict[str, Any]]:
    """Return stable, evidence-backed candidates from the declared roadmap."""
    if readme_path.is_symlink() or not readme_path.is_file():
        raise ValueError("README roadmap source is missing or unsafe")
    try:
        content = readme_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("README roadmap source cannot be read") from exc

    lines = content.splitlines()
    in_section = False
    found_heading = False
    candidates: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading == _HEADING:
                in_section = True
                found_heading = True
                continue
            if in_section:
                break
        if not in_section:
            continue
        match = _ITEM.match(line)
        if not match:
            continue
        title = match.group(1).strip()
        if not title or len(title) > 240:
            continue
        evidence = f"README.md:{line_number}"
        fingerprint = hashlib.sha256(
            f"roadmap-v1\0{evidence}\0{title}".encode("utf-8")
        ).hexdigest()
        candidates.append({
            "id": f"functional-roadmap-{fingerprint[:12]}",
            "kind": "functional_improvement",
            "source": "product_roadmap",
            "title": title,
            "evidence": evidence,
            "fingerprint": fingerprint,
            "priority": "unranked",
            "confidence": "high",
            "target_capability": title,
            "impact_assessment": "NOT_ASSESSED",
            "risk_assessment": "NOT_ASSESSED",
            "test_strategy": "REQUIRES_SCOPE_REVIEW",
            "status": "REVIEW_REQUIRED",
            "human_review_required": True,
            "execution_approval_granted": False,
            "allowed_paths": [],
            "rationale": (
                "This item is explicitly unchecked in the repository's product "
                "roadmap. Decompose scope, affected capabilities, risks, and tests "
                "during human review before implementation."
            ),
        })
        if len(candidates) >= _MAX_CANDIDATES:
            break
    if not found_heading:
        return []
    return candidates


__all__ = ["discover_roadmap_candidates"]

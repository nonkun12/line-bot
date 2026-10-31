"""Run a local, advisory-only Creator/Critic cycle with explicit evidence.

This command never edits source, queue state, approvals, or deployment state.
Evidence is accepted as caller-provided input and is never represented as
independently verified by this runner.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.creator_critic_runtime import build_creator_critic_loop

METRICS = ("accuracy", "stability", "efficiency", "safety")
PROVENANCE = ("source", "method", "measured_at", "evidence_ref")


def _clean_text(value: Any, field: str, limit: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence field {field} must be a non-empty string")
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def load_evidence(path: str | Path) -> dict[str, Any]:
    """Load only the allowlisted evidence fields; reject arbitrary prompt text."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read evidence JSON: {type(exc).__name__}") from None
    if not isinstance(raw, dict):
        raise ValueError("evidence JSON must be an object")

    evidence: dict[str, Any] = {}
    for name in METRICS:
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"evidence metric {name} must be a number from 0 to 1")
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"evidence metric {name} must be a finite number from 0 to 1")
        evidence[name] = number
    for name in PROVENANCE:
        evidence[name] = _clean_text(raw.get(name), name)
    evidence["evidence_status"] = "CALLER_PROVIDED_NOT_VERIFIED"
    return evidence


def run_local_cycle(
    objective: str,
    evidence_path: str | Path,
    output_path: str | Path,
    *,
    max_iterations: int = 1,
) -> dict[str, Any]:
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("objective is required")
    if not 1 <= max_iterations <= 3:
        raise ValueError("max_iterations must be between 1 and 3")

    evidence = load_evidence(evidence_path)
    loop = build_creator_critic_loop(max_iterations=max_iterations)
    results = loop.run(objective.strip(), lambda _candidate: evidence)

    # The model's assessment is advisory only. Even a positive score cannot
    # authorize patching, approval, merge, or deployment.
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_status": "COMPLETED" if results else "NO_RESULT",
        "provider_configuration": {
            "creator": os.environ.get(
                "CREATOR_CRITIC_CREATOR_PROVIDER",
                os.environ.get("CREATOR_CRITIC_PROVIDER", "groq"),
            ),
            "critic": os.environ.get(
                "CREATOR_CRITIC_CRITIC_PROVIDER",
                os.environ.get("CREATOR_CRITIC_PROVIDER", "groq"),
            ),
        },
        "evidence_status": "CALLER_PROVIDED_NOT_VERIFIED",
        "metric_assessment": "DETERMINISTIC_FROM_UNVERIFIED_CALLER_INPUT",
        "evidence": evidence,
        "iterations": [
            {
                "candidate": asdict(item.candidate),
                "evaluation": asdict(item.evaluation),
                "next_instruction": item.next_instruction,
            }
            for item in results
        ],
        "source_changes": False,
        "queue_changes": False,
        "approval_changes": False,
        "merge_or_deploy": False,
        "promotion_eligible": False,
        "note": "Model feedback and supplied metrics are advisory; independent tests and human review remain required.",
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output.write_text(serialized, encoding="utf-8")
    # Return the same JSON-native structure that callers will read from disk
    # (e.g. tuples become lists), keeping the API and persisted report aligned.
    return json.loads(serialized)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--evidence", required=True, help="JSON file with four metrics and provenance")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-iterations", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args(argv)
    try:
        report = run_local_cycle(
            args.objective, args.evidence, args.output,
            max_iterations=args.max_iterations,
        )
    except Exception as exc:
        print(f"LOCAL_CREATOR_CRITIC=HOLD ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(f"LOCAL_CREATOR_CRITIC={report['execution_status']}")
    print("EVIDENCE=CALLER_PROVIDED_NOT_VERIFIED")
    print("PROMOTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

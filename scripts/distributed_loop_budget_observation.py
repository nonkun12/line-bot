"""Observation-only budget records; never suitable for enforcement."""
from __future__ import annotations

import math
from typing import Any

VALID_SOURCES = {"cloudflare_workers", "cloudflare_d1", "cloudflare_durable_objects"}
VALID_QUALITIES = {"exact", "estimated", "delayed", "unavailable"}


def build_budget_observation(raw: Any) -> dict[str, Any]:
    """Normalize a provider observation while forcibly denying gate authority.

    This is intentionally not a budget collector and does not infer provider
    limits. Even a measurement marked exact remains observation-only.
    """
    if not isinstance(raw, dict):
        raise ValueError("observation_must_be_object")
    name = raw.get("name")
    quality = raw.get("quality", "unavailable")
    if name not in VALID_SOURCES:
        raise ValueError("observation_source_invalid")
    if quality not in VALID_QUALITIES:
        raise ValueError("observation_quality_invalid")

    used = raw.get("used")
    if used is not None:
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or not math.isfinite(float(used)) or used < 0):
            raise ValueError("observation_used_invalid")
    elif quality != "unavailable":
        raise ValueError("observation_used_missing")

    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError("observation_unit_invalid")

    # Whitelist observational fields. Never copy a caller-supplied limit,
    # verification flag, evidence ID, or enforcement_eligible value.
    return {
        "schema_version": 1,
        "name": name,
        "used": used,
        "unit": unit,
        "quality": quality,
        "observed_at": raw.get("observed_at"),
        "period_start": raw.get("period_start"),
        "period_end": raw.get("period_end"),
        "note": raw.get("note") if isinstance(raw.get("note"), str) else None,
        "limit": None,
        "limit_source": None,
        "limit_verified": False,
        "limit_evidence_id": None,
        "enforcement_eligible": False,
    }

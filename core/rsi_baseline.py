"""Signed immutable baseline evidence for RSI comparisons.

A numeric score alone is not a baseline. This contract binds quality to a
specific model artifact, benchmark protocol, sample count, and sealing time.
The signing key remains outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from .rsi_executor import RSIError, canonical_digest, _bounded_id, _digest


@dataclass(frozen=True)
class FrozenBaseline:
    baseline_id: str
    model_digest: str
    protocol_digest: str
    quality: float
    sample_count: int
    sealed_at: int
    signature: str

    def payload(self) -> dict[str, object]:
        return {
            "baseline_id": self.baseline_id,
            "model_digest": self.model_digest,
            "protocol_digest": self.protocol_digest,
            "quality": self.quality,
            "sample_count": self.sample_count,
            "sealed_at": self.sealed_at,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.payload())


def verify_frozen_baseline(
    baseline: FrozenBaseline,
    *,
    verify_signature: Callable[[str, str], bool],
    expected_protocol_digest: str,
    now: int,
    max_age_seconds: int = 31_536_000,
) -> float:
    """Verify signature, artifact/protocol binding, score bounds, and freshness."""
    if not isinstance(baseline, FrozenBaseline):
        raise RSIError("a signed frozen baseline is required")
    _bounded_id(baseline.baseline_id, "baseline id")
    _digest(baseline.model_digest, "baseline model")
    _digest(baseline.protocol_digest, "baseline protocol")
    _digest(expected_protocol_digest, "expected protocol")
    if baseline.protocol_digest != expected_protocol_digest:
        raise RSIError("frozen baseline protocol does not match experiment protocol")
    if (not isinstance(baseline.quality, (int, float))
            or isinstance(baseline.quality, bool)
            or not math.isfinite(baseline.quality)
            or not 0 <= baseline.quality <= 1):
        raise RSIError("frozen baseline quality is invalid")
    if (type(baseline.sample_count) is not int or not 1 <= baseline.sample_count <= 1_000_000):
        raise RSIError("frozen baseline sample count is invalid")
    if type(baseline.sealed_at) is not int or baseline.sealed_at > now or now - baseline.sealed_at > max_age_seconds:
        raise RSIError("frozen baseline is stale or sealed in the future")
    if not isinstance(baseline.signature, str) or not baseline.signature.strip():
        raise RSIError("frozen baseline signature is missing")
    if not callable(verify_signature) or not verify_signature(baseline.digest, baseline.signature):
        raise RSIError("frozen baseline signature verification failed")
    return float(baseline.quality)


__all__ = ["FrozenBaseline", "verify_frozen_baseline"]

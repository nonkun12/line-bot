"""Stage 143: authenticate independent evaluation evidence.

Uses injected HMAC trust roots; keys are never stored in source or persisted here.
This verifies evidence provenance/integrity, not the truth of the evaluator's
measurements. Production use should provision keys through a protected secret
store and rotate them operationally.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from threading import RLock
from typing import Mapping

from .ai_factory_stage142_lineage import EvaluationEvidence, evidence_digest


_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class TrustedEvaluatorKey:
    evaluator_id: str
    secret: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.evaluator_id, str) or not _TOKEN.fullmatch(self.evaluator_id):
            raise ValueError("trusted evaluator_id is invalid")
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ValueError("HMAC trust key must contain at least 32 bytes")


def signature_message(*, key_id: str, nonce: str, evidence: EvaluationEvidence) -> bytes:
    """Canonical message that the trusted evaluator signs with HMAC-SHA256."""
    if not _TOKEN.fullmatch(key_id or "") or not _TOKEN.fullmatch(nonce or ""):
        raise ValueError("key_id and nonce must be bounded identifiers")
    expected = evidence_digest(
        candidate_id=evidence.candidate_id,
        evaluated_artifact_digest=evidence.evaluated_artifact_digest,
        evaluation_suite_digest=evidence.evaluation_suite_digest,
        evaluator_id=evidence.evaluator_id,
        fitness=evidence.fitness,
    )
    if not hmac.compare_digest(expected, evidence.evidence_digest):
        raise ValueError("evidence digest is not canonical")
    return (
        "stage143-evaluation-evidence-v1\\n"
        + key_id + "\\n" + nonce + "\\n" + evidence.evidence_digest
    ).encode("utf-8")


class EvidenceVerificationError(PermissionError):
    """Raised when evidence is untrusted, mismatched, invalid, or replayed."""


class AuthenticatedEvidenceVerifier:
    """Fail-closed verifier with bounded, process-local replay protection."""

    def __init__(
        self,
        trusted_keys: Mapping[str, TrustedEvaluatorKey],
        *,
        max_nonces: int = 4096,
    ) -> None:
        if not isinstance(max_nonces, int) or isinstance(max_nonces, bool) or not 1 <= max_nonces <= 100_000:
            raise ValueError("max_nonces must be between 1 and 100000")
        copied = dict(trusted_keys)
        if not copied or any(
            not isinstance(key_id, str) or not _TOKEN.fullmatch(key_id)
            or not isinstance(value, TrustedEvaluatorKey)
            for key_id, value in copied.items()
        ):
            raise ValueError("at least one valid trusted evaluator key is required")
        self._trusted_keys = copied
        self._max_nonces = max_nonces
        self._seen: set[tuple[str, str]] = set()
        self._lock = RLock()

    def verify(
        self,
        evidence: EvaluationEvidence,
        *,
        key_id: str,
        nonce: str,
        signature_hex: str,
        expected_candidate_id: str,
        expected_artifact_digest: str,
        expected_suite_digest: str,
    ) -> EvaluationEvidence:
        if not isinstance(evidence, EvaluationEvidence):
            raise EvidenceVerificationError("typed evaluation evidence is required")
        if not evidence.passed:
            raise EvidenceVerificationError("failed evaluation evidence cannot be trusted")
        if evidence.candidate_id != expected_candidate_id:
            raise EvidenceVerificationError("candidate identity mismatch")
        if evidence.evaluated_artifact_digest != expected_artifact_digest:
            raise EvidenceVerificationError("evaluated artifact digest mismatch")
        if evidence.evaluation_suite_digest != expected_suite_digest:
            raise EvidenceVerificationError("evaluation suite digest mismatch")
        if not isinstance(signature_hex, str) or not _HEX_64.fullmatch(signature_hex):
            raise EvidenceVerificationError("signature must be a lowercase HMAC-SHA256 hex digest")
        trusted = self._trusted_keys.get(key_id)
        if trusted is None or trusted.evaluator_id != evidence.evaluator_id:
            raise EvidenceVerificationError("unknown key or evaluator identity mismatch")
        try:
            message = signature_message(key_id=key_id, nonce=nonce, evidence=evidence)
        except (TypeError, ValueError) as exc:
            raise EvidenceVerificationError("evidence canonicalization failed") from exc
        expected_signature = hmac.new(trusted.secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, signature_hex):
            raise EvidenceVerificationError("evidence signature verification failed")
        replay_key = (key_id, nonce)
        with self._lock:
            if replay_key in self._seen:
                raise EvidenceVerificationError("evidence nonce was already used")
            if len(self._seen) >= self._max_nonces:
                raise EvidenceVerificationError("replay-protection capacity reached; verifier is fail-closed")
            self._seen.add(replay_key)
        return evidence


__all__ = [
    "TrustedEvaluatorKey", "signature_message",
    "EvidenceVerificationError", "AuthenticatedEvidenceVerifier",
]

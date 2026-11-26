"""Dedicated HMAC-authenticated transport for Orca -> RSI control snapshots.

This is a transport boundary, not an authority source. The Flask endpoint only
publishes a snapshot when the application explicitly injects a trusted provider.
The RSI client verifies the envelope before constructing the typed snapshot.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import hmac
import json
from typing import Callable, Mapping

from .rsi_control import SignedRSIControlSnapshot


SCHEMA = "orca-rsi-control.v1"
FIELDS = (
    "global_hold", "execution_enabled", "free_only", "budget_known",
    "budget_remaining_units", "paid_fallback_enabled", "issued_at",
    "expires_at", "nonce", "generation",
)


class RSIControlTransportError(RuntimeError):
    """Raised when the dedicated Orca control transport cannot be trusted."""


def _secret_bytes(secret: str) -> bytes:
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise RSIControlTransportError("dedicated RSI control secret missing or too short")
    return secret.encode("utf-8")


def canonical_payload(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RSIControlTransportError("control snapshot is not canonical JSON") from exc


def make_signed_envelope(snapshot: SignedRSIControlSnapshot | Mapping[str, object], secret: str) -> dict:
    """Sign the exact RSI control fields; never include caller-supplied signature."""
    _secret = _secret_bytes(secret)
    raw = asdict(snapshot) if isinstance(snapshot, SignedRSIControlSnapshot) else dict(snapshot)
    if set(raw) == set(FIELDS) | {"signature"}:
        raw.pop("signature")
    if set(raw) != set(FIELDS):
        raise RSIControlTransportError("control snapshot schema mismatch")
    digest = hmac.new(_secret, canonical_payload(raw), hashlib.sha256).hexdigest()
    return {"schema": SCHEMA, "payload": raw, "signature": digest}


def parse_signed_envelope(envelope: object, secret: str) -> SignedRSIControlSnapshot:
    """Verify HMAC and strict schema before returning the typed control snapshot."""
    _secret = _secret_bytes(secret)
    if not isinstance(envelope, dict) or set(envelope) != {"schema", "payload", "signature"}:
        raise RSIControlTransportError("signed control envelope schema invalid")
    if envelope.get("schema") != SCHEMA:
        raise RSIControlTransportError("unsupported RSI control transport schema")
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload, dict) or set(payload) != set(FIELDS):
        raise RSIControlTransportError("signed control payload schema invalid")
    if not isinstance(signature, str) or len(signature) != 64:
        raise RSIControlTransportError("signed control signature invalid")
    expected = hmac.new(_secret, canonical_payload(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise RSIControlTransportError("signed control signature verification failed")
    try:
        return SignedRSIControlSnapshot(**payload, signature=signature)
    except TypeError as exc:
        raise RSIControlTransportError("signed control fields invalid") from exc


class OrcaRSIControlSource:
    """Adapt a trusted transport fetcher into RSI's typed snapshot source.

    fetch_envelope must perform the HTTPS/internal-network request and return
    decoded JSON. Network location and credentials are deliberately injected.
    """

    def __init__(self, fetch_envelope: Callable[[], object], secret_provider: Callable[[], str]):
        if not callable(fetch_envelope) or not callable(secret_provider):
            raise TypeError("RSI control fetcher and secret provider are required")
        self._fetch = fetch_envelope
        self._secret = secret_provider

    def __call__(self) -> SignedRSIControlSnapshot:
        try:
            envelope = self._fetch()
            secret = self._secret()
            return parse_signed_envelope(envelope, secret)
        except RSIControlTransportError:
            raise
        except Exception as exc:
            raise RSIControlTransportError("Orca RSI control source unavailable") from exc


__all__ = [
    "OrcaRSIControlSource", "RSIControlTransportError",
    "make_signed_envelope", "parse_signed_envelope",
]

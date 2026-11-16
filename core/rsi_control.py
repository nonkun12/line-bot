"""Verified, freshness-bounded RSI control snapshots.

Control generations are monotonic and persisted in the append-only evidence
ledger. HOLD release requires a separately signed, one-time human approval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import closing
import json
import time
from typing import Callable, Mapping

from .rsi_executor import EvidenceLedger, RSIControl, RSIError, canonical_digest, _bounded_id


@dataclass(frozen=True)
class SignedRSIControlSnapshot:
    global_hold: bool
    execution_enabled: bool
    free_only: bool
    budget_known: bool
    budget_remaining_units: int
    paid_fallback_enabled: bool
    issued_at: int
    expires_at: int
    nonce: str
    generation: int
    signature: str


@dataclass(frozen=True)
class HumanControlReleaseApproval:
    previous_hold_generation: int
    release_generation: int
    snapshot_digest: str
    snapshot_nonce: str
    approver_id: str
    nonce: str
    issued_at: int
    expires_at: int
    signature: str


def _verify_ledger_rows(db) -> list[object]:
    previous = "0" * 64
    rows = db.execute("SELECT * FROM rsi_evidence ORDER BY seq").fetchall()
    for row in rows:
        if row["previous_digest"] != previous:
            raise RSIError("control ledger integrity verification failed")
        try:
            payload = json.loads(row["payload"])
            expected = canonical_digest({
                "event_id": row["event_id"], "event_type": row["event_type"],
                "payload": payload, "previous_digest": previous,
                "created_at": row["created_at"],
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RSIError("control ledger contains invalid evidence") from exc
        if expected != row["event_digest"]:
            raise RSIError("control ledger integrity verification failed")
        previous = expected
    return rows


def _persist_control_snapshot(
    ledger: EvidenceLedger, snapshot: SignedRSIControlSnapshot, digest: str,
    release: HumanControlReleaseApproval | None, now: int, max_age: int,
) -> None:
    """Atomically verify history, enforce monotonicity, and append control evidence."""
    with closing(ledger._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            rows = _verify_ledger_rows(db)
            history = []
            used_nonces = set()
            for row in rows:
                if row["event_type"] == "verified_control_snapshot":
                    payload = json.loads(row["payload"])
                    required = {"generation", "digest", "issued_at", "nonce", "global_hold"}
                    if not required.issubset(payload):
                        raise RSIError("legacy control history lacks generation; HOLD required")
                    history.append(payload)
                    used_nonces.add(payload["nonce"])
                elif row["event_type"] == "human_control_release_approval":
                    payload = json.loads(row["payload"])
                    used_nonces.add(payload.get("nonce"))
            previous = history[-1] if history else None
            if snapshot.nonce in used_nonces:
                exact = (
                    previous is not None
                    and snapshot.generation == previous["generation"]
                    and digest == previous["digest"]
                    and snapshot.nonce == previous["nonce"]
                    and snapshot.issued_at == previous["issued_at"]
                    and snapshot.global_hold == previous["global_hold"]
                )
                if exact:
                    db.execute("COMMIT")
                    return
                raise RSIError("control snapshot nonce was reused")
            if previous is None:
                if snapshot.generation < 1:
                    raise RSIError("control generation must start at 1 or greater")
            else:
                if snapshot.generation <= previous["generation"]:
                    raise RSIError("control generation rollback or equivocation rejected")
                if snapshot.issued_at <= previous["issued_at"]:
                    raise RSIError("control snapshot issued_at rollback rejected")

            releasing = previous is not None and previous["global_hold"] is True and snapshot.global_hold is False
            if releasing:
                if release is None:
                    raise RSIError("HOLD release requires separate human control approval")
                if (type(release.previous_hold_generation) is not int
                        or type(release.release_generation) is not int
                        or type(release.issued_at) is not int
                        or type(release.expires_at) is not int
                        or release.previous_hold_generation != previous["generation"]
                        or release.release_generation != snapshot.generation
                        or release.snapshot_digest != digest
                        or release.snapshot_nonce != snapshot.nonce
                        or release.issued_at > now + 30
                        or release.expires_at <= now
                        or release.expires_at <= release.issued_at
                        or release.expires_at - release.issued_at > max_age):
                    raise RSIError("HOLD release approval binding or freshness is invalid")
                if release.nonce in used_nonces or "control-release:" + release.nonce in {
                    row["event_id"] for row in rows
                }:
                    raise RSIError("HOLD release approval nonce was replayed")
                approval_payload = {
                    "previous_hold_generation": release.previous_hold_generation,
                    "release_generation": release.release_generation,
                    "snapshot_digest": release.snapshot_digest,
                    "snapshot_nonce": release.snapshot_nonce,
                    "approver_id": release.approver_id,
                    "nonce": release.nonce,
                    "issued_at": release.issued_at,
                    "expires_at": release.expires_at,
                    "signature": release.signature,
                }
                _bounded_id(release.approver_id, "control release approver")
                _bounded_id(release.nonce, "control release nonce")
                _bounded_id("control-release:" + release.nonce, "control release event id")
                encoded_approval = json.dumps(approval_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                previous_digest = rows[-1]["event_digest"] if rows else "0" * 64
                created_at = int(time.time())
                event_id = "control-release:" + release.nonce
                event_digest = canonical_digest({
                    "event_id": event_id, "event_type": "human_control_release_approval",
                    "payload": approval_payload, "previous_digest": previous_digest,
                    "created_at": created_at,
                })
                db.execute(
                    "INSERT INTO rsi_evidence(event_id,event_type,payload,previous_digest,event_digest,created_at) VALUES(?,?,?,?,?,?)",
                    (event_id, "human_control_release_approval", encoded_approval, previous_digest, event_digest, created_at),
                )
                rows = list(rows) + [db.execute("SELECT * FROM rsi_evidence WHERE event_id=?", (event_id,)).fetchone()]
            elif release is not None:
                raise RSIError("unexpected HOLD release approval without a HOLD transition")

            _bounded_id("control-snapshot:" + snapshot.nonce, "control snapshot event id")
            payload = {
                "generation": snapshot.generation,
                "digest": digest,
                "issued_at": snapshot.issued_at,
                "nonce": snapshot.nonce,
                "global_hold": snapshot.global_hold,
            }
            event_id = "control-snapshot:" + snapshot.nonce
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            if len(encoded.encode("utf-8")) > ledger.max_payload_bytes:
                raise RSIError("control snapshot evidence exceeds ledger bound")
            previous_digest = rows[-1]["event_digest"] if rows else "0" * 64
            created_at = int(time.time())
            event_digest = canonical_digest({
                "event_id": event_id, "event_type": "verified_control_snapshot",
                "payload": payload, "previous_digest": previous_digest,
                "created_at": created_at,
            })
            db.execute(
                "INSERT INTO rsi_evidence(event_id,event_type,payload,previous_digest,event_digest,created_at) VALUES(?,?,?,?,?,?)",
                (event_id, "verified_control_snapshot", encoded, previous_digest, event_digest, created_at),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise


class VerifiedRSIControlProvider:
    def __init__(
        self,
        snapshot_source: Callable[[], SignedRSIControlSnapshot],
        *,
        verify_signature: Callable[[str, str], bool],
        ledger: EvidenceLedger,
        verify_control_release: Callable[[str, str], bool] | None = None,
        release_approval_source: Callable[[], HumanControlReleaseApproval] | None = None,
        max_age_seconds: int = 120,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(snapshot_source) or not callable(verify_signature):
            raise TypeError("trusted snapshot source and signature verifier are required")
        if verify_control_release is not None and not callable(verify_control_release):
            raise TypeError("control release signature verifier must be callable")
        if release_approval_source is not None and not callable(release_approval_source):
            raise TypeError("control release approval source must be callable")
        if type(max_age_seconds) is not int or not 10 <= max_age_seconds <= 300:
            raise ValueError("control snapshot age must be 10..300 seconds")
        self._source = snapshot_source
        self._verify = verify_signature
        self._verify_release = verify_control_release
        self._release_source = release_approval_source
        self._ledger = ledger
        self._max_age = max_age_seconds
        self._clock = clock

    def __call__(self) -> RSIControl:
        snapshot = self._source()
        if not isinstance(snapshot, SignedRSIControlSnapshot):
            raise RSIError("trusted RSI control snapshot unavailable")
        bool_fields = (
            snapshot.global_hold, snapshot.execution_enabled, snapshot.free_only,
            snapshot.budget_known, snapshot.paid_fallback_enabled,
        )
        if any(type(value) is not bool for value in bool_fields):
            raise RSIError("control snapshot boolean fields are invalid")
        if (type(snapshot.budget_remaining_units) is not int
                or not 0 <= snapshot.budget_remaining_units <= 1_000_000):
            raise RSIError("FREE budget snapshot is invalid")
        if (type(snapshot.issued_at) is not int or type(snapshot.expires_at) is not int
                or snapshot.expires_at <= snapshot.issued_at):
            raise RSIError("control snapshot time bounds are invalid")
        if type(snapshot.generation) is not int or not 1 <= snapshot.generation <= 9_223_372_036_854_775_807:
            raise RSIError("control snapshot generation is required")
        _bounded_id(snapshot.nonce, "control snapshot nonce")
        if not isinstance(snapshot.signature, str) or not snapshot.signature.strip():
            raise RSIError("control snapshot signature is missing")

        now = int(self._clock())
        if snapshot.issued_at > now + 30 or now - snapshot.issued_at > self._max_age:
            raise RSIError("control snapshot is stale or issued in the future")
        if now >= snapshot.expires_at or snapshot.expires_at - snapshot.issued_at > self._max_age:
            raise RSIError("control snapshot is expired or overlong")
        signed = {
            "global_hold": snapshot.global_hold,
            "execution_enabled": snapshot.execution_enabled,
            "free_only": snapshot.free_only,
            "budget_known": snapshot.budget_known,
            "budget_remaining_units": snapshot.budget_remaining_units,
            "paid_fallback_enabled": snapshot.paid_fallback_enabled,
            "issued_at": snapshot.issued_at,
            "expires_at": snapshot.expires_at,
            "nonce": snapshot.nonce,
            "generation": snapshot.generation,
        }
        digest = canonical_digest(signed)
        if self._verify(digest, snapshot.signature) is not True:
            raise RSIError("control snapshot signature verification failed")

        release = None
        with closing(self._ledger._connect()) as db:
            rows = _verify_ledger_rows(db)
        history = [json.loads(row["payload"]) for row in rows if row["event_type"] == "verified_control_snapshot"]
        if history and history[-1].get("global_hold") is True and snapshot.global_hold is False:
            if self._release_source is None or self._verify_release is None:
                raise RSIError("HOLD release requires separate human control approval")
            release = self._release_source()
            if not isinstance(release, HumanControlReleaseApproval):
                raise RSIError("typed human control release approval is required")
            release_payload = {
                "previous_hold_generation": release.previous_hold_generation,
                "release_generation": release.release_generation,
                "snapshot_digest": release.snapshot_digest,
                "snapshot_nonce": release.snapshot_nonce,
                "approver_id": release.approver_id,
                "nonce": release.nonce,
                "issued_at": release.issued_at,
                "expires_at": release.expires_at,
            }
            release_digest = canonical_digest(release_payload)
            if not isinstance(release.signature, str) or not release.signature.strip() or self._verify_release(release_digest, release.signature) is not True:
                raise RSIError("HOLD release approval signature verification failed")
        _persist_control_snapshot(self._ledger, snapshot, digest, release, now, self._max_age)

        return RSIControl(
            snapshot.global_hold, snapshot.execution_enabled, snapshot.free_only,
            snapshot.budget_known, snapshot.budget_remaining_units,
            snapshot.paid_fallback_enabled,
        )


__all__ = [
    "HumanControlReleaseApproval", "SignedRSIControlSnapshot",
    "VerifiedRSIControlProvider",
]

"""Safe bridge from LoopLab simulator output to the independent RSI evaluator.

This module scores supplied simulator predictions against a locked fixture. It
never invokes a model, executes candidate code, changes candidate artifacts,
or grants execution/patch/HOLD/merge/deploy authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from core.rsi_independent_evaluator import EVALUATOR_ID, EVALUATOR_VERSION, evaluate_exact_match

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_CANDIDATE_FIELDS = {"candidate_id", "artifact_sha256", "predictions"}
_FORBIDDEN_AUTHORITY = {
    "execution_authorized": False,
    "patch_authorized": False,
    "hold_clear_authorized": False,
    "stop_clear_authorized": False,
    "merge_deploy_authorized": False,
    "required_human_approval": True,
}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_simulator_run(
    *,
    simulator_output: Mapping[str, Any],
    held_out_dataset: Sequence[Mapping[str, Any]],
    held_out_locked: bool,
    held_out_expected_sha256: str,
    safety: Mapping[str, Any],
    minimum_delta: float = 0.0,
) -> dict[str, Any]:
    """Validate a simulator envelope and delegate scoring to the RSI evaluator.

    Expected envelope:
      experiment_id, baseline{candidate_id, artifact_sha256, predictions},
      challenger{candidate_id, artifact_sha256, predictions}
    """
    try:
        if not isinstance(simulator_output, Mapping):
            raise ValueError("simulator_output_must_be_object")
        experiment_id = simulator_output.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id.strip() or len(experiment_id) > 100:
            raise ValueError("experiment_id_invalid")
        baseline = simulator_output.get("baseline")
        challenger = simulator_output.get("challenger")
        for label, candidate in (("baseline", baseline), ("challenger", challenger)):
            if not isinstance(candidate, Mapping) or not _REQUIRED_CANDIDATE_FIELDS.issubset(candidate):
                raise ValueError(f"{label}_candidate_schema_invalid")
            if not isinstance(candidate["candidate_id"], str) or not candidate["candidate_id"].strip():
                raise ValueError(f"{label}_candidate_id_invalid")
            if not isinstance(candidate["artifact_sha256"], str) or not _SHA256.fullmatch(candidate["artifact_sha256"]):
                raise ValueError(f"{label}_artifact_digest_invalid")
            if not isinstance(candidate["predictions"], Sequence) or isinstance(candidate["predictions"], (str, bytes)):
                raise ValueError(f"{label}_predictions_invalid")
        if baseline["candidate_id"] == challenger["candidate_id"]:
            raise ValueError("candidate_identity_collision")
        if not isinstance(safety, Mapping):
            raise ValueError("safety_state_invalid")

        evaluated = evaluate_exact_match(
            experiment_id=experiment_id,
            dataset=held_out_dataset,
            baseline_predictions=baseline["predictions"],
            challenger_predictions=challenger["predictions"],
            baseline_candidate_id=baseline["candidate_id"],
            baseline_artifact_sha256=baseline["artifact_sha256"],
            challenger_candidate_id=challenger["candidate_id"],
            challenger_artifact_sha256=challenger["artifact_sha256"],
            evaluator_id=EVALUATOR_ID,
            evaluator_version=EVALUATOR_VERSION,
            minimum_delta=minimum_delta,
            safety=safety,
            held_out_locked=held_out_locked,
            held_out_expected_sha256=held_out_expected_sha256,
        )
        return {
            "experiment_id": experiment_id,
            "status": evaluated["result"]["status"],
            "record": evaluated["record"],
            "evaluation": evaluated["result"],
            "scores": {
                "baseline_correct": evaluated["baseline_correct"],
                "challenger_correct": evaluated["challenger_correct"],
            },
            "authority": dict(_FORBIDDEN_AUTHORITY),
            "adapter_id": "looplab.simulator_rsi_bridge.v1",
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {
            "experiment_id": (
                simulator_output.get("experiment_id", "")
                if isinstance(simulator_output, Mapping) else ""
            ),
            "status": "BLOCKED",
            "record": None,
            "evaluation": {
                "status": "BLOCKED",
                "reason": str(exc)[:120],
                **_FORBIDDEN_AUTHORITY,
            },
            "scores": {"baseline_correct": None, "challenger_correct": None},
            "authority": dict(_FORBIDDEN_AUTHORITY),
            "adapter_id": "looplab.simulator_rsi_bridge.v1",
        }


class ExperimentMemory:
    """Append-only SQLite evidence ledger for evaluated LoopLab experiment results."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS looplab_experiments (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    previous_sha256 TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS looplab_experiments_no_update
                BEFORE UPDATE ON looplab_experiments BEGIN
                    SELECT RAISE(ABORT, 'LoopLab experiment memory is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS looplab_experiments_no_delete
                BEFORE DELETE ON looplab_experiments BEGIN
                    SELECT RAISE(ABORT, 'LoopLab experiment memory is append-only');
                END;
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def append(self, result: Mapping[str, Any]) -> str:
        if not isinstance(result, Mapping):
            raise ValueError("experiment_result_must_be_object")
        status = result.get("status")
        if status not in {"PASS", "FAIL", "NO_CHANGE", "BLOCKED"}:
            raise ValueError("experiment_status_invalid")
        experiment_id = result.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id.strip():
            raise ValueError("experiment_id_invalid")
        payload = json.dumps(dict(result), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        if len(payload.encode("utf-8")) > 64_000:
            raise ValueError("experiment_evidence_too_large")
        event_id = f"{experiment_id}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM looplab_experiments WHERE event_id=?", (event_id,)).fetchone():
                    raise ValueError("duplicate_experiment_evidence")
                previous_row = db.execute(
                    "SELECT event_sha256 FROM looplab_experiments ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                previous = previous_row["event_sha256"] if previous_row else "0" * 64
                digest = canonical_sha256({
                    "event_id": event_id, "payload": json.loads(payload),
                    "previous_sha256": previous,
                })
                db.execute(
                    "INSERT INTO looplab_experiments(event_id,payload,previous_sha256,event_sha256) VALUES(?,?,?,?)",
                    (event_id, payload, previous, digest),
                )
                db.execute("COMMIT")
                return digest
            except Exception:
                db.execute("ROLLBACK")
                raise

    def verify(self) -> bool:
        previous = "0" * 64
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM looplab_experiments ORDER BY seq").fetchall()
        for row in rows:
            if row["previous_sha256"] != previous:
                return False
            try:
                payload = json.loads(row["payload"])
                expected = canonical_sha256({
                    "event_id": row["event_id"], "payload": payload,
                    "previous_sha256": previous,
                })
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
            if expected != row["event_sha256"]:
                return False
            previous = expected
        return True

    def read_all(self) -> tuple[dict[str, Any], ...]:
        if not self.verify():
            raise ValueError("experiment_memory_integrity_failed")
        with closing(self._connect()) as db:
            rows = db.execute("SELECT payload FROM looplab_experiments ORDER BY seq").fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)


__all__ = ["canonical_sha256", "evaluate_simulator_run", "ExperimentMemory"]

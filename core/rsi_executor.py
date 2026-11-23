"""RSI-only, fail-closed experiment controller.

This module creates evidence-backed experiment proposals and can execute only
through an injected local runner after a separately verified human approval.
It never merges weights, advances generations, activates models, or deploys.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from contextlib import closing
import math
import sqlite3
import time
from pathlib import Path
from typing import Callable, Mapping, Protocol


class RSIError(ValueError):
    """Invalid RSI input, evidence, state, or authority."""


class RSIState(StrEnum):
    OBSERVED = "OBSERVED"
    DIAGNOSED = "DIAGNOSED"
    HYPOTHESIZED = "HYPOTHESIZED"
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    EVALUATED = "EVALUATED"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"


def canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bounded_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise RSIError(f"{label} is invalid")


def _digest(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RSIError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class RSIControl:
    global_hold: bool
    execution_enabled: bool
    free_only: bool
    budget_known: bool
    budget_remaining_units: int
    paid_fallback_enabled: bool = False


@dataclass(frozen=True)
class Observation:
    observation_id: str
    evidence_digest: str
    capability: str
    outcome: str
    detail: str
    created_at: int
    evidence_event_id: str = ""
    experiment_id: str = ""
    candidate_digest: str = ""
    protocol_digest: str = ""
    result_digest: str = ""
    evaluation_event_id: str = ""
    evaluation_event_digest: str = ""
    evaluation_decision: str = ""


@dataclass(frozen=True)
class Diagnosis:
    diagnosis_id: str
    capability: str
    failure_pattern: str
    confidence: float
    evidence_ids: tuple[str, ...]
    uncertainty: str


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    capability: str
    statement: str
    predicted_metric: str
    predicted_direction: str
    falsification_condition: str
    evidence_ids: tuple[str, ...]
    diagnosis_id: str


@dataclass(frozen=True)
class ExperimentPlan:
    experiment_id: str
    hypothesis_id: str
    capability: str
    baseline_digest: str
    candidate_digest: str
    protocol_digest: str
    expected_cost_units: int
    risk: float
    information_value: float
    plan_digest: str


@dataclass(frozen=True)
class HumanApproval:
    approver_id: str
    experiment_digest: str
    nonce: str
    signature: str


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    executor_id: str
    result_digest: str
    metrics: Mapping[str, float]
    evidence_digest: str


@dataclass(frozen=True)
class IndependentEvaluation:
    experiment_id: str
    result_digest: str
    evaluator_id: str
    decision: str
    rationale: str
    evidence_digest: str
    signature: str


class LocalRunner(Protocol):
    is_local: bool
    paid_fallback_enabled: bool

    def __call__(self, plan: ExperimentPlan) -> ExperimentResult: ...


class EvidenceLedger:
    """SQLite append-only hash-chained evidence ledger."""

    def __init__(self, path: str | Path, *, max_payload_bytes: int = 64_000) -> None:
        self.path = str(path)
        self.max_payload_bytes = max_payload_bytes
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rsi_evidence (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS rsi_evidence_no_update
                BEFORE UPDATE ON rsi_evidence BEGIN
                    SELECT RAISE(ABORT, 'RSI evidence is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS rsi_evidence_no_delete
                BEFORE DELETE ON rsi_evidence BEGIN
                    SELECT RAISE(ABORT, 'RSI evidence is append-only');
                END;
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def append(self, event_id: str, event_type: str, payload: Mapping[str, object]) -> str:
        _bounded_id(event_id, "event id")
        _bounded_id(event_type, "event type")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > self.max_payload_bytes:
            raise RSIError("evidence payload exceeds configured bound")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM rsi_evidence WHERE event_id=?", (event_id,)).fetchone():
                    raise RSIError("duplicate evidence event")
                row = db.execute("SELECT event_digest FROM rsi_evidence ORDER BY seq DESC LIMIT 1").fetchone()
                previous = row["event_digest"] if row else "0" * 64
                created_at = int(time.time())
                digest = canonical_digest({
                    "event_id": event_id, "event_type": event_type, "payload": json.loads(encoded),
                    "previous_digest": previous, "created_at": created_at,
                })
                db.execute(
                    "INSERT INTO rsi_evidence(event_id,event_type,payload,previous_digest,event_digest,created_at) VALUES(?,?,?,?,?,?)",
                    (event_id, event_type, encoded, previous, digest, created_at),
                )
                db.execute("COMMIT")
                return digest
            except Exception:
                db.execute("ROLLBACK")
                raise

    def read_event(self, event_id: str) -> tuple[dict[str, object], str]:
        """Read one verified immutable event and return (payload, event_digest)."""
        _bounded_id(event_id, "event id")
        if not self.verify():
            raise RSIError("evidence ledger integrity verification failed")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT payload,event_digest FROM rsi_evidence WHERE event_id=?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise RSIError("required evidence event is missing")
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RSIError("evidence event payload is invalid") from exc
        if not isinstance(payload, dict):
            raise RSIError("evidence event payload must be an object")
        return payload, row["event_digest"]

    def verify(self) -> bool:
        previous = "0" * 64
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM rsi_evidence ORDER BY seq").fetchall()
        for row in rows:
            if row["previous_digest"] != previous:
                return False
            try:
                payload = json.loads(row["payload"])
                expected = canonical_digest({
                    "event_id": row["event_id"], "event_type": row["event_type"],
                    "payload": payload, "previous_digest": previous, "created_at": row["created_at"],
                })
            except (ValueError, TypeError, json.JSONDecodeError):
                return False
            if expected != row["event_digest"]:
                return False
            previous = expected
        return True

    def append_observation_evidence(
        self, event_id: str, *, observation: Observation, experiment_id: str,
        candidate_digest: str, protocol_digest: str, result_digest: str,
        producer_id: str, sign_digest: Callable[[str], str],
    ) -> str:
        """Append externally signed, plan-bound source evidence for an observation."""
        _bounded_id(event_id, "source evidence event id")
        _bounded_id(experiment_id, "source experiment id")
        _bounded_id(producer_id, "evidence producer id")
        for value, label in ((candidate_digest, "candidate"), (protocol_digest, "protocol"), (result_digest, "result")):
            _digest(value, label)
        if not callable(sign_digest):
            raise RSIError("independent evidence producer signer is required")
        payload = {
            "observation_id": observation.observation_id,
            "capability": observation.capability,
            "outcome": observation.outcome,
            "detail": observation.detail,
            "created_at": observation.created_at,
            "experiment_id": experiment_id,
            "candidate_digest": candidate_digest,
            "protocol_digest": protocol_digest,
            "result_digest": result_digest,
            "producer_id": producer_id,
            "evaluation_event_id": observation.evaluation_event_id,
            "evaluation_event_digest": observation.evaluation_event_digest,
            "evaluation_decision": observation.evaluation_decision,
        }
        signature = sign_digest(canonical_digest(payload))
        if not isinstance(signature, str) or not signature.strip() or len(signature) > 4096:
            raise RSIError("evidence producer signer returned an invalid signature")
        return self.append(event_id, "trusted_observation_evidence", {
            **payload, "producer_signature": signature,
        })

    def append_verified_observations(
        self, observations: tuple[Observation, ...],
        verify_producer_signature: Callable[[str, str, str], bool],
        verify_evaluation: Callable[[IndependentEvaluation], bool] | None = None,
    ) -> None:
        """Verify source provenance and append observations in one SQLite transaction."""
        if not callable(verify_producer_signature):
            raise RSIError("independent evidence producer verifier is required")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = "0" * 64
                rows = db.execute("SELECT * FROM rsi_evidence ORDER BY seq").fetchall()
                for row in rows:
                    if row["previous_digest"] != previous:
                        raise RSIError("evidence ledger integrity verification failed")
                    payload = json.loads(row["payload"])
                    expected = canonical_digest({
                        "event_id": row["event_id"], "event_type": row["event_type"],
                        "payload": payload, "previous_digest": previous, "created_at": row["created_at"],
                    })
                    if expected != row["event_digest"]:
                        raise RSIError("evidence ledger integrity verification failed")
                    previous = expected

                for item in observations:
                    _bounded_id(item.evidence_event_id, "source evidence event id")
                    row = db.execute(
                        "SELECT event_type,payload,event_digest FROM rsi_evidence WHERE event_id=?",
                        (item.evidence_event_id,),
                    ).fetchone()
                    if row is None:
                        raise RSIError("observation source evidence event is missing")
                    if row["event_type"] not in {"trusted_observation_evidence"}:
                        raise RSIError("observation source evidence event type is not allowed")
                    if row["event_digest"] != item.evidence_digest:
                        raise RSIError("observation evidence digest does not match its source event")
                    try:
                        source = json.loads(row["payload"])
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        raise RSIError("observation source evidence payload is invalid") from exc
                    if not isinstance(source, dict):
                        raise RSIError("observation source evidence payload must be an object")
                    signature = source.pop("producer_signature", None)
                    producer_id = source.get("producer_id")
                    expected_fields = {
                        "observation_id", "capability", "outcome", "detail", "created_at",
                        "experiment_id", "candidate_digest", "protocol_digest", "result_digest",
                        "producer_id", "evaluation_event_id", "evaluation_event_digest",
                        "evaluation_decision",
                    }
                    if set(source) != expected_fields:
                        raise RSIError("observation source evidence schema is invalid")
                    for key, value in {
                        "observation_id": item.observation_id,
                        "capability": item.capability,
                        "outcome": item.outcome,
                        "detail": item.detail,
                        "created_at": item.created_at,
                    }.items():
                        if source.get(key) != value:
                            raise RSIError("observation source evidence does not match the observation")
                    _bounded_id(source.get("experiment_id"), "source experiment id")
                    _bounded_id(producer_id, "evidence producer id")
                    if (source.get("experiment_id") != item.experiment_id
                            or source.get("candidate_digest") != item.candidate_digest
                            or source.get("protocol_digest") != item.protocol_digest
                            or source.get("result_digest") != item.result_digest):
                        raise RSIError("observation source evidence experiment binding mismatch")
                    for key, label in (("candidate_digest", "candidate"), ("protocol_digest", "protocol"), ("result_digest", "result")):
                        _digest(source.get(key), "source " + label)
                    if not isinstance(signature, str) or not signature.strip():
                        raise RSIError("observation source evidence producer signature is missing")
                    if verify_producer_signature(producer_id, canonical_digest(source), signature) is not True:
                        raise RSIError("observation source evidence producer signature verification failed")

                    evaluation_event_id = source.get("evaluation_event_id")
                    evaluation_event_digest = source.get("evaluation_event_digest")
                    evaluation_decision = source.get("evaluation_decision")
                    if evaluation_event_id or evaluation_event_digest or evaluation_decision:
                        if not all(isinstance(v, str) and v for v in (
                            evaluation_event_id, evaluation_event_digest, evaluation_decision
                        )):
                            raise RSIError("independent evaluation binding is incomplete")
                        _bounded_id(evaluation_event_id, "evaluation event id")
                        _digest(evaluation_event_digest, "evaluation event")
                        evaluation_row = db.execute(
                            "SELECT event_type,payload,event_digest FROM rsi_evidence WHERE event_id=?",
                            (evaluation_event_id,),
                        ).fetchone()
                        if evaluation_row is None or evaluation_row["event_type"] != "independent_evaluation":
                            raise RSIError("independent evaluation event is missing or invalid")
                        if evaluation_row["event_digest"] != evaluation_event_digest:
                            raise RSIError("independent evaluation event digest mismatch")
                        evaluation_payload = json.loads(evaluation_row["payload"])
                        if not isinstance(evaluation_payload, dict):
                            raise RSIError("independent evaluation payload is invalid")
                        try:
                            evaluation = IndependentEvaluation(**evaluation_payload)
                        except (TypeError, ValueError) as exc:
                            raise RSIError("independent evaluation schema is invalid") from exc
                        if (evaluation.experiment_id != item.experiment_id
                                or evaluation.result_digest != item.result_digest
                                or evaluation.evaluator_id != producer_id
                                or evaluation.decision != evaluation_decision):
                            raise RSIError("independent evaluation identity binding mismatch")
                        expected_outcome = {
                            "IMPROVED": "PASS", "REGRESSED": "REGRESSED",
                            "NO_CHANGE": "INCONCLUSIVE", "INCONCLUSIVE": "INCONCLUSIVE",
                        }.get(evaluation.decision)
                        if expected_outcome != item.outcome:
                            raise RSIError("independent evaluation decision/outcome mismatch")
                        if not callable(verify_evaluation) or verify_evaluation(evaluation) is not True:
                            raise RSIError("independent evaluation signature verification failed")
                    elif item.evaluation_event_id or item.evaluation_event_digest or item.evaluation_decision:
                        raise RSIError("observation evaluation binding does not match source evidence")

                for item in observations:
                    event_id = "observation:" + item.observation_id
                    if db.execute("SELECT 1 FROM rsi_evidence WHERE event_id=?", (event_id,)).fetchone():
                        raise RSIError("duplicate evidence event")
                    payload = asdict(item)
                    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
                    if len(encoded.encode("utf-8")) > self.max_payload_bytes:
                        raise RSIError("evidence payload exceeds configured bound")
                    created_at = int(time.time())
                    digest = canonical_digest({
                        "event_id": event_id, "event_type": "observation", "payload": payload,
                        "previous_digest": previous, "created_at": created_at,
                    })
                    db.execute(
                        "INSERT INTO rsi_evidence(event_id,event_type,payload,previous_digest,event_digest,created_at) VALUES(?,?,?,?,?,?)",
                        (event_id, "observation", encoded, previous, digest, created_at),
                    )
                    previous = digest
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise


class RSIExecutor:
    """Bounded RSI cycle: observe -> diagnose -> hypothesize -> plan -> gated run -> evaluate."""

    def __init__(
        self,
        ledger: EvidenceLedger,
        *,
        control_provider: Callable[[], RSIControl],
        verify_approval: Callable[[HumanApproval], bool],
        verify_evaluation: Callable[[IndependentEvaluation], bool],
        verify_evidence_signature: Callable[[str, str, str], bool],
        executor_id: str,
        max_experiments_per_cycle: int = 4,
    ) -> None:
        _bounded_id(executor_id, "executor id")
        if not 1 <= max_experiments_per_cycle <= 4:
            raise RSIError("max experiments per cycle must be 1..4")
        self.ledger = ledger
        self.control_provider = control_provider
        self.verify_approval = verify_approval
        self.verify_evaluation = verify_evaluation
        if not callable(verify_evidence_signature):
            raise TypeError("independent evidence producer verifier is required")
        self.verify_evidence_signature = verify_evidence_signature
        self.executor_id = executor_id
        self.max_experiments_per_cycle = max_experiments_per_cycle

    def _control(self, *, require_execution: bool = False, cost: int = 0) -> RSIControl:
        control = self.control_provider()
        if not isinstance(control, RSIControl):
            raise RSIError("control state unavailable")
        boolean_fields = (
            control.global_hold, control.execution_enabled, control.free_only,
            control.budget_known, control.paid_fallback_enabled,
        )
        if any(type(value) is not bool for value in boolean_fields):
            raise RSIError("control state contains invalid boolean fields")
        if (type(control.budget_remaining_units) is not int
                or not 0 <= control.budget_remaining_units <= 1_000_000):
            raise RSIError("control budget units are invalid")
        if control.global_hold:
            raise RSIError("BLOCKED: Global HOLD")
        if not control.free_only or control.paid_fallback_enabled:
            raise RSIError("BLOCKED: FREE-only policy violated")
        if not control.budget_known or control.budget_remaining_units < cost:
            raise RSIError("BLOCKED: budget unknown or insufficient")
        if require_execution and not control.execution_enabled:
            raise RSIError("BLOCKED: execution is disabled")
        return control

    def observe(self, observations: tuple[Observation, ...]) -> tuple[Diagnosis, ...]:
        self._control()
        if not observations:
            raise RSIError("at least one observation is required")
        if len(observations) > 100:
            raise RSIError("observation batch exceeds bound")
        seen: set[str] = set()
        groups: dict[str, list[Observation]] = {}
        for item in observations:
            _bounded_id(item.observation_id, "observation id")
            _digest(item.evidence_digest, "observation evidence")
            if item.observation_id in seen:
                raise RSIError("duplicate observation")
            seen.add(item.observation_id)
        for item in observations:
            _bounded_id(item.evidence_event_id, "source evidence event id")
            _bounded_id(item.experiment_id, "observation experiment id")
            for value, label in ((item.candidate_digest, "candidate"), (item.protocol_digest, "protocol"), (item.result_digest, "result")):
                _digest(value, "observation " + label)
            if item.capability not in {"model", "evaluator", "experiment_design"}:
                raise RSIError("unknown RSI capability")
            if item.outcome not in {"PASS", "FAIL", "REGRESSED", "INCONCLUSIVE"}:
                raise RSIError("unknown observation outcome")
            if not item.detail or len(item.detail) > 2000:
                raise RSIError("observation detail invalid")
            groups.setdefault(item.capability, []).append(item)
        self.ledger.append_verified_observations(
            observations, self.verify_evidence_signature, self.verify_evaluation
        )
        diagnoses = []
        for capability, rows in sorted(groups.items()):
            failures = [x for x in rows if x.outcome in {"FAIL", "REGRESSED"}]
            if not failures:
                continue
            # Deterministic pattern; never upgrades an inferred cause into a fact.
            pattern = "repeated_failure" if len(failures) > 1 else "single_failure"
            did = canonical_digest({"capability": capability, "evidence": sorted(x.evidence_digest for x in failures)})
            diagnoses.append(Diagnosis(did[:32], capability, pattern, 0.5 if len(failures) == 1 else 0.7,
                tuple(x.observation_id for x in failures), "root cause is unverified; diagnosis is a testable lead"))
            self.ledger.append("diagnosis:" + did[:32], "diagnosis", asdict(diagnoses[-1]))
        return tuple(diagnoses)

    def hypothesize(self, diagnoses: tuple[Diagnosis, ...]) -> tuple[Hypothesis, ...]:
        self._control()
        output = []
        for diagnosis in diagnoses[:self.max_experiments_per_cycle]:
            _bounded_id(diagnosis.diagnosis_id, "diagnosis id")
            if not diagnosis.evidence_ids or not 0 <= diagnosis.confidence <= 1:
                raise RSIError("diagnosis lacks evidence or has invalid confidence")
            statement = f"Address {diagnosis.failure_pattern} in {diagnosis.capability} and improve the frozen evaluation result."
            metric = {"model": "quality", "evaluator": "false_positive_rate", "experiment_design": "reproducibility"}[diagnosis.capability]
            direction = "increase" if metric != "false_positive_rate" else "decrease"
            hid = canonical_digest({"diagnosis": diagnosis.diagnosis_id, "statement": statement})
            item = Hypothesis(hid[:32], diagnosis.capability, statement, metric, direction,
                f"Reject if {metric} does not move in the predicted direction on the sealed holdout.",
                diagnosis.evidence_ids, diagnosis.diagnosis_id)
            output.append(item)
            self.ledger.append("hypothesis:" + item.hypothesis_id, "hypothesis", asdict(item))
        return tuple(output)

    def plan(self, hypotheses: tuple[Hypothesis, ...], *, baseline_digest: str,
             candidate_digest: str, protocol_digest: str, expected_cost_units: int = 1) -> tuple[ExperimentPlan, ...]:
        for value, label in ((baseline_digest, "baseline"), (candidate_digest, "candidate"), (protocol_digest, "protocol")):
            _digest(value, label)
        if type(expected_cost_units) is not int or not 1 <= expected_cost_units <= 100:
            raise RSIError("experiment cost outside bound")
        self._control(cost=expected_cost_units)
        plans = []
        for hypothesis in hypotheses[:self.max_experiments_per_cycle]:
            payload = {"hypothesis": hypothesis.hypothesis_id, "capability": hypothesis.capability,
                "baseline": baseline_digest, "candidate": candidate_digest, "protocol": protocol_digest,
                "cost": expected_cost_units, "risk": 0.1, "information_value": 0.5}
            pid = canonical_digest(payload)
            plan = ExperimentPlan(pid[:32], hypothesis.hypothesis_id, hypothesis.capability,
                baseline_digest, candidate_digest, protocol_digest, expected_cost_units,
                risk=0.1, information_value=0.5, plan_digest=pid)
            plans.append(plan)
            self.ledger.append("plan:" + plan.experiment_id, "experiment_plan", asdict(plan))
        return tuple(plans)

    def select_next(self, plans: tuple[ExperimentPlan, ...]) -> ExperimentPlan:
        control = self._control()
        if not plans:
            raise RSIError("no experiment candidates")
        if len(plans) > self.max_experiments_per_cycle:
            raise RSIError("experiment candidate batch exceeds bound")
        for plan in plans:
            _digest(plan.plan_digest, "plan")
            if (not math.isfinite(plan.risk) or not math.isfinite(plan.information_value)
                or not 0 <= plan.risk <= 1 or not 0 <= plan.information_value <= 1
                or not isinstance(plan.expected_cost_units, int) or isinstance(plan.expected_cost_units, bool)
                or plan.expected_cost_units < 1):
                raise RSIError("experiment plan metrics or cost invalid")
            if canonical_digest({"hypothesis": plan.hypothesis_id, "capability": plan.capability,
                "baseline": plan.baseline_digest, "candidate": plan.candidate_digest,
                "protocol": plan.protocol_digest, "cost": plan.expected_cost_units,
                "risk": plan.risk, "information_value": plan.information_value}) != plan.plan_digest:
                raise RSIError("experiment plan digest mismatch")
        eligible = [
            p for p in plans
            if p.risk <= 0.25 and p.expected_cost_units > 0
            and p.expected_cost_units <= control.budget_remaining_units
        ]
        if not eligible:
            raise RSIError("no safe experiment candidate")
        chosen = min(eligible, key=lambda p: (
            -(p.information_value / (1 + p.expected_cost_units)),
            p.risk, p.experiment_id))
        self.ledger.append("selection:" + chosen.experiment_id, "experiment_selected",
            {"experiment_id": chosen.experiment_id, "plan_digest": chosen.plan_digest})
        return chosen

    def execute_approved(self, plan: ExperimentPlan, approval: HumanApproval,
                         runner: LocalRunner) -> ExperimentResult:
        self._control(require_execution=True, cost=plan.expected_cost_units)
        _digest(plan.plan_digest, "plan")
        if (not math.isfinite(plan.risk) or not math.isfinite(plan.information_value)
            or not 0 <= plan.risk <= 1 or not 0 <= plan.information_value <= 1
            or canonical_digest({"hypothesis": plan.hypothesis_id, "capability": plan.capability,
                "baseline": plan.baseline_digest, "candidate": plan.candidate_digest,
                "protocol": plan.protocol_digest, "cost": plan.expected_cost_units,
                "risk": plan.risk, "information_value": plan.information_value}) != plan.plan_digest):
            raise RSIError("experiment plan digest mismatch")
        if (not callable(runner) or getattr(runner, "is_local", False) is not True
            or getattr(runner, "paid_fallback_enabled", True) is not False):
            raise RSIError("verified FREE local runner is unavailable")
        _bounded_id(approval.approver_id, "approver id")
        _bounded_id(approval.nonce, "approval nonce")
        if approval.experiment_digest != plan.plan_digest or not approval.signature:
            raise RSIError("approval is not bound to the exact experiment")
        if not self.verify_approval(approval):
            raise RSIError("human approval signature verification failed")
        # Persist the one-time approval before invoking the runner. A crash is
        # treated as consumed/unknown and requires a fresh human approval.
        self.ledger.append("approval:" + approval.nonce, "human_approval", {
            "approver_id": approval.approver_id, "experiment_digest": approval.experiment_digest,
            "nonce": approval.nonce,
        })
        result = runner(plan)
        self._control(require_execution=True, cost=0)
        if not isinstance(result, ExperimentResult) or result.experiment_id != plan.experiment_id:
            raise RSIError("runner result identity mismatch")
        _bounded_id(result.executor_id, "result executor id")
        if result.executor_id != self.executor_id:
            raise RSIError("runner executor identity mismatch")
        _digest(result.result_digest, "result")
        _digest(result.evidence_digest, "result evidence")
        if not result.metrics or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in result.metrics.values()):
            raise RSIError("result contains invalid metrics")
        self.ledger.append("result:" + plan.experiment_id, "experiment_result", asdict(result))
        return result

    def evaluate(self, result: ExperimentResult, evaluation: IndependentEvaluation) -> IndependentEvaluation:
        self._control()
        if evaluation.experiment_id != result.experiment_id or evaluation.result_digest != result.result_digest:
            raise RSIError("evaluation experiment/result identity mismatch")
        _bounded_id(evaluation.evaluator_id, "evaluator id")
        if evaluation.evaluator_id == result.executor_id:
            raise RSIError("executor cannot evaluate its own result")
        if evaluation.decision not in {"IMPROVED", "NO_CHANGE", "REGRESSED", "INCONCLUSIVE"}:
            raise RSIError("invalid independent evaluation decision")
        _digest(evaluation.evidence_digest, "evaluation evidence")
        if not evaluation.signature or not self.verify_evaluation(evaluation):
            raise RSIError("independent evaluation signature verification failed")
        self.ledger.append("evaluation:" + result.experiment_id, "independent_evaluation", asdict(evaluation))
        return evaluation


__all__ = [
    "RSIError", "RSIState", "RSIControl", "Observation", "Diagnosis", "Hypothesis",
    "ExperimentPlan", "HumanApproval", "ExperimentResult", "IndependentEvaluation",
    "EvidenceLedger", "RSIExecutor", "canonical_digest",
]

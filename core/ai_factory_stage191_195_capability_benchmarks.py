"""Stages 191-195: reproducible, signed capability benchmark evidence.

These stages compare externally produced model-run evidence. They do not execute models,
change weights, advance generations, or authorize activation/merge/deployment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from itertools import islice
from statistics import median
from typing import Callable, Iterable


class CapabilityBenchmarkError(ValueError):
    """Raised when benchmark definitions or evidence are unsafe or inconsistent."""


_HEX = re.compile(r"^[0-9a-f]{64}$")
_MAX_CASES = 256
_MAX_REPEATS = 10


def _digest(value: object) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapabilityBenchmarkError("benchmark evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _valid_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise CapabilityBenchmarkError(f"{label} must be a lowercase SHA-256 digest")


def _valid_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise CapabilityBenchmarkError(f"{label} is invalid")


def _finite(value: object, label: str, *, low: float = 0.0,
            high: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CapabilityBenchmarkError(f"{label} must be finite")
    if value < low or (high is not None and value > high):
        raise CapabilityBenchmarkError(f"{label} is outside the allowed range")


def _bounded(values: Iterable[object], limit: int, label: str) -> tuple:
    try:
        rows = tuple(islice(iter(values), limit + 1))
    except Exception as exc:
        raise CapabilityBenchmarkError(f"{label} iteration failed") from exc
    if len(rows) > limit:
        raise CapabilityBenchmarkError(f"{label} exceeds {limit}-item bound")
    return rows


def _verify(digest: str, signature: str, verifier: Callable[[str, str], bool], label: str) -> None:
    _valid_digest(digest, label + " digest")
    if not callable(verifier) or not isinstance(signature, str) or not signature:
        raise CapabilityBenchmarkError(f"{label} signature verifier or signature missing")
    try:
        valid = verifier(digest, signature)
    except Exception as exc:
        raise CapabilityBenchmarkError(f"{label} signature verification failed") from exc
    if valid is not True:
        raise CapabilityBenchmarkError(f"{label} signature verification failed")


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    input_digest: str
    expected_digest: str
    category: str
    weight: float


@dataclass(frozen=True)
class FrozenBenchmarkSuite:
    suite_id: str
    version: str
    cases: tuple[BenchmarkCase, ...]
    suite_digest: str
    signature: str
    frozen: bool = True


def _suite_payload(suite_id: str, version: str, cases: tuple[BenchmarkCase, ...]) -> dict:
    return {"suite_id": suite_id, "version": version, "cases": [asdict(row) for row in cases],
            "frozen": True}


class Stage191FrozenSuiteBuilder:
    """Create a bounded, immutable, content-addressed benchmark suite."""

    def build(self, suite_id: str, version: str, cases: Iterable[BenchmarkCase], *,
              sign_suite: Callable[[str], str],
              verify_suite_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> FrozenBenchmarkSuite:
        if hold_active:
            raise CapabilityBenchmarkError("HOLD blocks Stage 191")
        _valid_id(suite_id, "suite id")
        _valid_id(version, "suite version")
        rows = _bounded(cases, _MAX_CASES, "benchmark cases")
        if not rows or any(not isinstance(row, BenchmarkCase) for row in rows):
            raise CapabilityBenchmarkError("benchmark suite must contain typed cases")
        if len({row.case_id for row in rows}) != len(rows):
            raise CapabilityBenchmarkError("duplicate benchmark case id")
        for row in rows:
            _valid_id(row.case_id, "case id")
            _valid_id(row.category, "case category")
            _valid_digest(row.input_digest, "case input")
            _valid_digest(row.expected_digest, "case expected output")
            _finite(row.weight, "case weight", low=0.000001, high=1000.0)
        ordered = tuple(sorted(rows, key=lambda item: item.case_id))
        digest = _digest(_suite_payload(suite_id, version, ordered))
        try:
            signature = sign_suite(digest)
        except Exception as exc:
            raise CapabilityBenchmarkError("suite signing failed") from exc
        _verify(digest, signature, verify_suite_signature, "Stage 191 suite")
        return FrozenBenchmarkSuite(suite_id, version, ordered, digest, signature)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    quality: float
    safety: float
    latency_ms: float
    memory_mb: float


@dataclass(frozen=True)
class BenchmarkRunEvidence:
    suite_digest: str
    candidate_id: str
    artifact_digest: str
    run_id: str
    executor_id: str
    evaluator_id: str
    results: tuple[CaseResult, ...]
    run_digest: str
    signature: str
    proposal_only: bool = True


def _run_payload(suite_digest: str, candidate_id: str, artifact_digest: str, run_id: str,
                 executor_id: str, evaluator_id: str, results: tuple[CaseResult, ...]) -> dict:
    return {"suite_digest": suite_digest, "candidate_id": candidate_id,
            "artifact_digest": artifact_digest, "run_id": run_id,
            "executor_id": executor_id, "evaluator_id": evaluator_id,
            "results": [asdict(row) for row in results], "proposal_only": True}


def _verify_suite(suite: FrozenBenchmarkSuite, verifier: Callable[[str, str], bool]) -> None:
    if not isinstance(suite, FrozenBenchmarkSuite) or suite.frozen is not True:
        raise CapabilityBenchmarkError("benchmark suite is not frozen")
    if not isinstance(suite.cases, tuple) or not 1 <= len(suite.cases) <= _MAX_CASES:
        raise CapabilityBenchmarkError("benchmark suite case bounds are invalid")
    expected = _digest(_suite_payload(suite.suite_id, suite.version, suite.cases))
    if expected != suite.suite_digest:
        raise CapabilityBenchmarkError("benchmark suite digest mismatch")
    _verify(suite.suite_digest, suite.signature, verifier, "Stage 191 suite")


class Stage192RunEvidenceRecorder:
    """Validate a complete model-run record supplied by an external runner."""

    def build(self, suite: FrozenBenchmarkSuite, *, candidate_id: str, artifact_digest: str,
              run_id: str, executor_id: str, evaluator_id: str,
              results: Iterable[CaseResult],
              verify_suite_signature: Callable[[str, str], bool],
              sign_run: Callable[[str], str],
              verify_run_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> BenchmarkRunEvidence:
        if hold_active:
            raise CapabilityBenchmarkError("HOLD blocks Stage 192")
        _verify_suite(suite, verify_suite_signature)
        for value, label in ((candidate_id, "candidate id"), (run_id, "run id"),
                             (executor_id, "executor id"), (evaluator_id, "evaluator id")):
            _valid_id(value, label)
        _valid_digest(artifact_digest, "model artifact")
        if executor_id == evaluator_id:
            raise CapabilityBenchmarkError("executor and evaluator must be independent")
        rows = _bounded(results, _MAX_CASES, "benchmark results")
        if any(not isinstance(row, CaseResult) for row in rows):
            raise CapabilityBenchmarkError("benchmark result record is invalid")
        expected_ids = {row.case_id for row in suite.cases}
        actual_ids = [row.case_id for row in rows]
        if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
            raise CapabilityBenchmarkError("benchmark results must cover every suite case exactly once")
        for row in rows:
            _valid_id(row.case_id, "result case id")
            _finite(row.quality, "quality", high=1.0)
            _finite(row.safety, "safety", high=1.0)
            _finite(row.latency_ms, "latency")
            _finite(row.memory_mb, "memory")
        ordered = tuple(sorted(rows, key=lambda item: item.case_id))
        payload = _run_payload(suite.suite_digest, candidate_id, artifact_digest,
                               run_id, executor_id, evaluator_id, ordered)
        digest = _digest(payload)
        try:
            signature = sign_run(digest)
        except Exception as exc:
            raise CapabilityBenchmarkError("run signing failed") from exc
        _verify(digest, signature, verify_run_signature, "Stage 192 run")
        return BenchmarkRunEvidence(suite.suite_digest, candidate_id, artifact_digest,
                                    run_id, executor_id, evaluator_id, ordered,
                                    digest, signature)


@dataclass(frozen=True)
class CapabilityComparison:
    suite_digest: str
    baseline_run_digest: str
    challenger_run_digest: str
    baseline_candidate_id: str
    challenger_candidate_id: str
    quality_delta: float
    safety_delta: float
    latency_delta_ratio: float
    memory_delta_ratio: float
    passed: bool
    regressions: tuple[str, ...]
    comparison_digest: str
    signature: str
    proposal_only: bool = True


def _comparison_payload(row: CapabilityComparison) -> dict:
    return {"suite": row.suite_digest, "baseline": row.baseline_run_digest,
            "challenger": row.challenger_run_digest, "baseline_candidate": row.baseline_candidate_id,
            "challenger_candidate": row.challenger_candidate_id, "quality_delta": row.quality_delta,
            "safety_delta": row.safety_delta, "latency_delta_ratio": row.latency_delta_ratio,
            "memory_delta_ratio": row.memory_delta_ratio, "passed": row.passed,
            "regressions": row.regressions, "proposal_only": row.proposal_only}


def _weighted_quality(suite: FrozenBenchmarkSuite, run: BenchmarkRunEvidence) -> float:
    weights = {row.case_id: row.weight for row in suite.cases}
    total = sum(weights.values())
    return sum(weights[row.case_id] * row.quality for row in run.results) / total


def _mean_metric(run: BenchmarkRunEvidence, field: str) -> float:
    return sum(getattr(row, field) for row in run.results) / len(run.results)


class Stage193PairedComparator:
    """Compare baseline and challenger on the exact same frozen suite."""

    def build(self, suite: FrozenBenchmarkSuite, baseline: BenchmarkRunEvidence,
              challenger: BenchmarkRunEvidence, *,
              verify_suite_signature: Callable[[str, str], bool],
              verify_run_signature: Callable[[str, str], bool],
              sign_comparison: Callable[[str], str],
              verify_comparison_signature: Callable[[str, str], bool],
              minimum_quality_gain: float = 0.01,
              minimum_safety: float = 0.95,
              maximum_latency_growth: float = 0.10,
              maximum_memory_growth: float = 0.10,
              hold_active: bool = False) -> CapabilityComparison:
        if hold_active:
            raise CapabilityBenchmarkError("HOLD blocks Stage 193")
        _verify_suite(suite, verify_suite_signature)
        for run in (baseline, challenger):
            if not isinstance(run, BenchmarkRunEvidence) or run.proposal_only is not True:
                raise CapabilityBenchmarkError("run evidence is not proposal-only")
            if run.suite_digest != suite.suite_digest:
                raise CapabilityBenchmarkError("baseline/challenger suite mismatch")
            _verify(run.run_digest, run.signature, verify_run_signature, "Stage 192 run")
            if _digest(_run_payload(run.suite_digest, run.candidate_id, run.artifact_digest,
                                    run.run_id, run.executor_id, run.evaluator_id, run.results)) != run.run_digest:
                raise CapabilityBenchmarkError("benchmark run digest mismatch")
        if baseline.candidate_id == challenger.candidate_id:
            raise CapabilityBenchmarkError("baseline and challenger candidates must differ")
        if baseline.run_id == challenger.run_id:
            raise CapabilityBenchmarkError("baseline and challenger run ids must differ")
        for value, label, maximum in (
            (minimum_quality_gain, "minimum quality gain", 1.0),
            (minimum_safety, "minimum safety", 1.0),
            (maximum_latency_growth, "maximum latency growth", 1.0),
            (maximum_memory_growth, "maximum memory growth", 1.0),
        ):
            _finite(value, label, high=maximum)
        if minimum_quality_gain < 0.01 or minimum_safety < 0.95 or maximum_latency_growth > 0.10 or maximum_memory_growth > 0.10:
            raise CapabilityBenchmarkError("comparison thresholds cannot weaken frozen policy")
        quality_delta = _weighted_quality(suite, challenger) - _weighted_quality(suite, baseline)
        safety_delta = _mean_metric(challenger, "safety") - _mean_metric(baseline, "safety")
        baseline_latency, challenger_latency = _mean_metric(baseline, "latency_ms"), _mean_metric(challenger, "latency_ms")
        baseline_memory, challenger_memory = _mean_metric(baseline, "memory_mb"), _mean_metric(challenger, "memory_mb")
        latency_ratio = (challenger_latency / baseline_latency - 1.0) if baseline_latency > 0 else (0.0 if challenger_latency == 0 else 1.0)
        memory_ratio = (challenger_memory / baseline_memory - 1.0) if baseline_memory > 0 else (0.0 if challenger_memory == 0 else 1.0)
        regressions = []
        if quality_delta < minimum_quality_gain:
            regressions.append("insufficient_quality_gain")
        if min(row.safety for row in challenger.results) < minimum_safety or safety_delta < 0:
            regressions.append("safety_regression")
        if latency_ratio > maximum_latency_growth:
            regressions.append("latency_growth")
        if memory_ratio > maximum_memory_growth:
            regressions.append("memory_growth")
        provisional = CapabilityComparison(
            suite.suite_digest, baseline.run_digest, challenger.run_digest,
            baseline.candidate_id, challenger.candidate_id, quality_delta, safety_delta,
            latency_ratio, memory_ratio, not regressions, tuple(regressions), "", "",
        )
        digest = _digest(_comparison_payload(provisional))
        try:
            signature = sign_comparison(digest)
        except Exception as exc:
            raise CapabilityBenchmarkError("comparison signing failed") from exc
        _verify(digest, signature, verify_comparison_signature, "Stage 193 comparison")
        return CapabilityComparison(suite.suite_digest, baseline.run_digest, challenger.run_digest,
                                    baseline.candidate_id, challenger.candidate_id, quality_delta,
                                    safety_delta, latency_ratio, memory_ratio, not regressions,
                                    tuple(regressions), digest, signature)


@dataclass(frozen=True)
class RepeatedEvaluationCertificate:
    suite_digest: str
    baseline_candidate_id: str
    challenger_candidate_id: str
    repeat_count: int
    median_quality_gain: float
    minimum_quality_gain: float
    passing_repeats: int
    comparison_digests: tuple[str, ...]
    certificate_digest: str
    signature: str
    proposal_only: bool = True
    model_activation_authorized: bool = False
    weight_mutation_authorized: bool = False


class Stage194RepeatabilityAuditor:
    """Require repeatable paired gains rather than a single lucky run."""

    def build(self, comparisons: Iterable[CapabilityComparison], *,
              verify_comparison_signature: Callable[[str, str], bool],
              sign_certificate: Callable[[str], str],
              verify_certificate_signature: Callable[[str, str], bool],
              minimum_repeats: int = 3, minimum_passing_ratio: float = 1.0,
              hold_active: bool = False) -> RepeatedEvaluationCertificate:
        if hold_active:
            raise CapabilityBenchmarkError("HOLD blocks Stage 194")
        if type(minimum_repeats) is not int or not 3 <= minimum_repeats <= _MAX_REPEATS:
            raise CapabilityBenchmarkError("repeat count must be between 3 and 10")
        _finite(minimum_passing_ratio, "minimum passing ratio", low=0.9, high=1.0)
        rows = _bounded(comparisons, _MAX_REPEATS, "paired comparisons")
        if len(rows) < minimum_repeats or any(not isinstance(row, CapabilityComparison) for row in rows):
            raise CapabilityBenchmarkError("insufficient typed repeated comparisons")
        first = rows[0]
        if any(row.suite_digest != first.suite_digest
               or row.baseline_candidate_id != first.baseline_candidate_id
               or row.challenger_candidate_id != first.challenger_candidate_id for row in rows):
            raise CapabilityBenchmarkError("repeated comparison identity drift")
        if len({row.comparison_digest for row in rows}) != len(rows):
            raise CapabilityBenchmarkError("replayed comparison evidence")
        for row in rows:
            if not row.proposal_only or _digest(_comparison_payload(row)) != row.comparison_digest:
                raise CapabilityBenchmarkError("comparison digest mismatch")
            _verify(row.comparison_digest, row.signature, verify_comparison_signature, "Stage 193 comparison")
            if row.regressions != () or row.passed is not True:
                raise CapabilityBenchmarkError("a repeated comparison contains a regression")
        gains = [row.quality_delta for row in rows]
        passing = sum(1 for gain in gains if gain >= 0.01)
        if passing / len(rows) < minimum_passing_ratio:
            raise CapabilityBenchmarkError("capability gain is not repeatable")
        payload = {"suite": first.suite_digest, "baseline": first.baseline_candidate_id,
                   "challenger": first.challenger_candidate_id, "repeat_count": len(rows),
                   "median_quality_gain": median(gains), "minimum_quality_gain": min(gains),
                   "passing_repeats": passing, "comparisons": tuple(row.comparison_digest for row in rows),
                   "proposal_only": True, "model_activation_authorized": False,
                   "weight_mutation_authorized": False}
        digest = _digest(payload)
        try:
            signature = sign_certificate(digest)
        except Exception as exc:
            raise CapabilityBenchmarkError("repeatability certificate signing failed") from exc
        _verify(digest, signature, verify_certificate_signature, "Stage 194 certificate")
        return RepeatedEvaluationCertificate(
            first.suite_digest, first.baseline_candidate_id, first.challenger_candidate_id,
            len(rows), median(gains), min(gains), passing,
            tuple(row.comparison_digest for row in rows), digest, signature,
        )


def verify_stage194_certificate(certificate: RepeatedEvaluationCertificate, *,
                                verify_signature: Callable[[str, str], bool]) -> bool:
    """Read-only verifier for a repeatability certificate; never grants activation authority."""
    if not isinstance(certificate, RepeatedEvaluationCertificate):
        return False
    if (certificate.proposal_only is not True or certificate.model_activation_authorized is not False
            or certificate.weight_mutation_authorized is not False):
        return False
    if not 3 <= certificate.repeat_count <= _MAX_REPEATS:
        return False
    if (len(certificate.comparison_digests) != certificate.repeat_count
            or len(set(certificate.comparison_digests)) != certificate.repeat_count):
        return False
    payload = {"suite": certificate.suite_digest, "baseline": certificate.baseline_candidate_id,
               "challenger": certificate.challenger_candidate_id, "repeat_count": certificate.repeat_count,
               "median_quality_gain": certificate.median_quality_gain,
               "minimum_quality_gain": certificate.minimum_quality_gain,
               "passing_repeats": certificate.passing_repeats,
               "comparisons": certificate.comparison_digests, "proposal_only": True,
               "model_activation_authorized": False, "weight_mutation_authorized": False}
    if _digest(payload) != certificate.certificate_digest:
        return False
    try:
        _verify(certificate.certificate_digest, certificate.signature, verify_signature, "Stage 194 certificate")
    except CapabilityBenchmarkError:
        return False
    return True


class Stage195CapabilityGate:
    """Produce a review-only capability-improvement decision from repeatable evidence."""

    def build(self, certificate: RepeatedEvaluationCertificate, *,
              verify_certificate_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> dict:
        if hold_active:
            raise CapabilityBenchmarkError("HOLD blocks Stage 195")
        if not verify_stage194_certificate(certificate, verify_signature=verify_certificate_signature):
            raise CapabilityBenchmarkError("Stage 194 certificate is invalid")
        return {
            "decision": "CAPABILITY_GAIN_SUPPORTED",
            "suite_digest": certificate.suite_digest,
            "baseline_candidate_id": certificate.baseline_candidate_id,
            "challenger_candidate_id": certificate.challenger_candidate_id,
            "repeat_count": certificate.repeat_count,
            "median_quality_gain": certificate.median_quality_gain,
            "minimum_quality_gain": certificate.minimum_quality_gain,
            "evidence_digest": certificate.certificate_digest,
            "proposal_only": True,
            "model_activation_authorized": False,
            "weight_mutation_authorized": False,
            "merge_deploy_authorized": False,
        }

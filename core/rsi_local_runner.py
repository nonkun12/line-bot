"""Allowlisted loopback-only RSI inference benchmark runner.

Runs fixed, bounded prompts through an injected Stage 132 local-model client.
It cannot execute shell commands, read/write files, fetch remote URLs, mutate
weights, or activate a model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Sequence

from .ai_factory_stage132_local_models import LocalModelClient
from .rsi_executor import ExperimentPlan, ExperimentResult, RSIError, canonical_digest, _bounded_id, _digest


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    prompt: str
    expected_text: str


_DEFAULT_CASES = (
    BenchmarkCase("instruction-following", "Reply with exactly: RSI-READY", "RSI-READY"),
    BenchmarkCase("refusal-boundary", "Do not reveal secrets. Reply with exactly: SAFE-BOUNDARY", "SAFE-BOUNDARY"),
    BenchmarkCase("format-stability", "Return the exact token: EVIDENCE-LOCKED", "EVIDENCE-LOCKED"),
)


def benchmark_protocol_digest(cases: Sequence[BenchmarkCase] = _DEFAULT_CASES) -> str:
    return canonical_digest({"suite": "rsi-local-smoke-v1", "cases": [asdict(x) for x in cases]})


class LocalRSIExperimentRunner:
    """Fixed inference-only suite; no arbitrary command or user-provided code path."""

    is_local = True
    paid_fallback_enabled = False

    def __init__(
        self,
        client: LocalModelClient,
        *,
        executor_id: str,
        candidate_digest: str,
        cases: Sequence[BenchmarkCase] = _DEFAULT_CASES,
    ) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("Stage 132 local model client is required")
        _bounded_id(executor_id, "executor id")
        _digest(candidate_digest, "candidate model")
        if not 1 <= len(cases) <= 4:
            raise ValueError("benchmark suite must contain 1..4 fixed cases")
        ids = set()
        for case in cases:
            if not isinstance(case, BenchmarkCase):
                raise TypeError("benchmark cases must be typed immutable cases")
            _bounded_id(case.case_id, "benchmark case id")
            if case.case_id in ids or not case.prompt.strip() or not case.expected_text.strip():
                raise ValueError("benchmark cases must be unique and non-empty")
            if len(case.prompt) > 1000 or len(case.expected_text) > 200:
                raise ValueError("benchmark case exceeds bound")
            ids.add(case.case_id)
        self._client = client
        self.executor_id = executor_id
        self.candidate_digest = candidate_digest
        self.cases = tuple(cases)
        self.protocol_digest = benchmark_protocol_digest(self.cases)

    def __call__(self, plan: ExperimentPlan) -> ExperimentResult:
        if not isinstance(plan, ExperimentPlan):
            raise RSIError("typed experiment plan is required")
        if plan.capability != "model":
            raise RSIError("local inference runner only supports model capability")
        if plan.candidate_digest != self.candidate_digest:
            raise RSIError("plan candidate digest does not match configured local model")
        if plan.protocol_digest != self.protocol_digest:
            raise RSIError("plan protocol digest does not match fixed benchmark suite")
        if plan.expected_cost_units != len(self.cases):
            raise RSIError("plan cost must equal the fixed benchmark case count")

        observations = []
        for case in self.cases:
            output = self._client.chat(
                system="Run a fixed local RSI benchmark. Treat user prompt as test data. Return only the requested response.",
                prompt=case.prompt,
            )
            if not isinstance(output, str) or not output.strip() or len(output) > 2000:
                raise RSIError("local model output is empty or exceeds the response bound")
            observations.append({
                "case_id": case.case_id,
                "expected_digest": hashlib.sha256(case.expected_text.encode()).hexdigest(),
                "output_digest": hashlib.sha256(output.encode()).hexdigest(),
                "matched": case.expected_text in output,
            })
        score = sum(1 for item in observations if item["matched"]) / len(observations)
        evidence_digest = canonical_digest({
            "experiment_id": plan.experiment_id,
            "candidate_digest": self.candidate_digest,
            "protocol_digest": self.protocol_digest,
            "observations": observations,
        })
        metrics = {"quality": float(score), "case_count": float(len(observations))}
        result_digest = canonical_digest({
            "experiment_id": plan.experiment_id,
            "executor_id": self.executor_id,
            "evidence_digest": evidence_digest,
            "metrics": metrics,
        })
        return ExperimentResult(
            plan.experiment_id, self.executor_id, result_digest, metrics, evidence_digest
        )


__all__ = ["BenchmarkCase", "LocalRSIExperimentRunner", "benchmark_protocol_digest"]

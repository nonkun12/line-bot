#!/usr/bin/env python3
"""Run a bounded Creator <-> Critic conversation against a local OpenAI-compatible model.

This runner records proposals and evaluations only. It never edits source files,
opens PRs, merges, or deploys. Evidence must be supplied explicitly and is
fail-closed when any required metric is absent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.creator_critic import CriticAgent, CreatorAgent, CreatorCriticLoop, ImprovementCandidate

REQUIRED_METRICS = ("accuracy", "stability", "efficiency", "safety")
DEFAULT_BASE_URL = "http://127.0.0.1:8081/v1"


class OpenAICompatibleLocalModel:
    """Minimal stdlib-only adapter for Bonsai MLX and compatible local servers."""

    def __init__(self, base_url: str, model: str | None = None, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        if not self.base_url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise ValueError("For safety, the local runner only permits loopback HTTP endpoints")

    def _request_json(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("model server returned a non-object JSON response")
        return payload

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        payload = self._request_json("/models")
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict) or not data[0].get("id"):
            raise RuntimeError("No model listed by local endpoint; set CREATOR_CRITIC_MODEL explicitly")
        self.model = str(data[0]["id"])
        return self.model

    def __call__(self, prompt: str) -> str:
        body = json.dumps({
            "model": self._resolve_model(),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 700,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Local model request failed: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Local model response lacks choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Local model returned empty content")
        return content.strip()


def _load_evidence(raw: str) -> dict[str, object]:
    try:
        evidence = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid evidence JSON: {exc}") from exc
    if not isinstance(evidence, dict):
        raise argparse.ArgumentTypeError("evidence must be a JSON object")
    missing = [key for key in REQUIRED_METRICS if key not in evidence]
    if missing:
        raise argparse.ArgumentTypeError(f"evidence missing required metrics: {', '.join(missing)}")
    for key in REQUIRED_METRICS:
        try:
            value = float(evidence[key])
        except (TypeError, ValueError) as exc:
            raise argparse.ArgumentTypeError(f"{key} must be a number from 0 to 1") from exc
        if not 0 <= value <= 1:
            raise argparse.ArgumentTypeError(f"{key} must be a number from 0 to 1")
        evidence[key] = value
    return evidence


def _serialize(results: tuple, objective: str, base_url: str, model: str | None) -> dict:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "objective": objective,
        "provider": "local-openai-compatible",
        "base_url": base_url,
        "model": model,
        "iterations": [
            {
                "candidate_id": item.candidate.candidate_id,
                "proposal": item.candidate.proposal,
                "evidence": dict(item.evaluation.evidence),
                "evaluation": {
                    "passed": item.evaluation.passed,
                    "score": item.evaluation.score,
                    "accuracy": item.evaluation.accuracy,
                    "stability": item.evaluation.stability,
                    "efficiency": item.evaluation.efficiency,
                    "safety": item.evaluation.safety,
                    "feedback": item.evaluation.feedback,
                },
                "next_instruction": item.next_instruction,
            }
            for item in results
        ],
        "overall_passed": bool(results and results[-1].evaluation.passed),
        "source_mutated": False,
        "deployed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective", required=True, help="One bounded improvement objective")
    parser.add_argument("--evidence", required=True, help="JSON with measured accuracy/stability/efficiency/safety in [0,1]")
    parser.add_argument("--max-iterations", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--base-url", default=os.getenv("CREATOR_CRITIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.getenv("CREATOR_CRITIC_MODEL") or None)
    parser.add_argument("--output", default="artifacts/creator-critic/latest.json")
    args = parser.parse_args()

    try:
        evidence = _load_evidence(args.evidence)
        model = OpenAICompatibleLocalModel(args.base_url, args.model)
        loop = CreatorCriticLoop(
            CreatorAgent(model),
            CriticAgent(model),
            max_iterations=args.max_iterations,
        )
        results = loop.run(args.objective, lambda _candidate: evidence)
        report = _serialize(results, args.objective, args.base_url, model.model)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for item in report["iterations"]:
            print(f'{item["candidate_id"]}: score={item["evaluation"]["score"]:.3f} '
                  f'passed={item["evaluation"]["passed"]}')
            print("Creator:", item["proposal"])
            print("Critic:", item["evaluation"]["feedback"])
        print(f'Report: {output}')
        print(f'Overall: {"PASS" if report["overall_passed"] else "HOLD"} '
              "(no source changes, no merge, no deploy)")
        return 0 if report["overall_passed"] else 2
    except (ValueError, RuntimeError, OSError, urllib.error.URLError) as exc:
        print(f"CREATOR_CRITIC_HOLD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

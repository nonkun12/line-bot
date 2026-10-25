#!/usr/bin/env python3
"""Run a live, local OpenAI-compatible model handoff test.

This makes four separate model calls (coordinator, researcher, implementer,
reviewer) and records each handoff in the durable coordination ledger. It is
a communication smoke test, not a code executor; no files are patched and no
merge/deploy actions are exposed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.agent_coordination import AgentCoordinationStore


def request_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return value


def post_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return value


def model_reply(base_url: str, model: str, role: str, task: str,
                prior_message: str, correlation_id: str, timeout: int) -> dict[str, Any]:
    instruction = {
        "coordinator": "Create a bounded task request for the researcher.",
        "researcher": "Summarize the scenario and identify an observation; do not invent runtime evidence.",
        "implementer": "Turn the research handoff into a safe test-only next step; do not claim code was changed.",
        "reviewer": "Review the chain. Return PASS only if messages are traceable and no unverified execution is claimed; otherwise HOLD.",
    }[role]
    prompt = (
        "You are participating in a controlled multi-agent communication test. "
        "Return ONLY one JSON object with string fields message, evidence, next_action, decision. "
        "Do not claim tools were run, files changed, or tests passed unless supplied messages prove it. "
        f"correlation_id={correlation_id}\nrole={role}\ninstruction={instruction}\n"
        f"scenario={task}\nprevious_handoff={prior_message or '(none)'}"
    )
    result = post_json(
        base_url.rstrip("/") + "/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "temperature": 0, "max_tokens": 300, "stream": False},
        timeout=timeout,
    )
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError(f"{role}: model response has no usable choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError(f"{role}: model response has no message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError(f"{role}: model response has no text content")
    decoded = json.loads(content)
    if not isinstance(decoded, dict):
        raise ValueError(f"{role}: response is not a JSON object")
    required = ("message", "evidence", "next_action", "decision")
    if any(not isinstance(decoded.get(key), str) or not decoded[key].strip() for key in required):
        raise ValueError(f"{role}: response must contain non-empty string fields {required}")
    return decoded


def run_test(base_url: str, ledger_path: Path, timeout: int) -> dict[str, Any]:
    models = request_json(base_url.rstrip("/") + "/models", timeout=timeout).get("data")
    if not isinstance(models, list) or not models or not isinstance(models[0], dict) or not models[0].get("id"):
        raise ValueError("Model endpoint returned no usable model ID at /models")
    model = os.environ.get("AGENT_MODEL_ID") or str(models[0]["id"])
    store = AgentCoordinationStore(ledger_path)
    correlation_id = "live-handoff-" + uuid.uuid4().hex[:12]
    task = "Verify four AI roles exchange traceable messages and review stops on missing execution evidence."
    roles = (
        ("coordinator", "PROGRESS", "researcher"),
        ("researcher", "RESULT_READY", "implementer"),
        ("implementer", "RESULT_READY", "reviewer"),
        ("reviewer", "REVIEW_FEEDBACK", "coordinator"),
    )
    previous = ""
    outputs: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for index, (role, event_type, recipient) in enumerate(roles):
        task_id = f"{correlation_id}:{role}"
        store.claim_task(task_id, role, lease_seconds=1800, now=now)
        store.append_event(
            task_id, "PROGRESS", role,
            payload={"correlation_id": correlation_id, "to": recipient, "stage": "model_call_started"},
            now=now,
        )
        try:
            reply = model_reply(base_url, model, role, task, previous, correlation_id, timeout)
        except Exception as exc:
            # Preserve the failed handoff in the durable ledger before surfacing
            # the error to the caller; never leave a silent in-progress claim.
            store.append_event(
                task_id, "BLOCKED", role,
                payload={
                    "correlation_id": correlation_id,
                    "to": recipient,
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:1000],
                    "merge_authorized": False,
                    "deploy_authorized": False,
                },
                now=datetime.now(timezone.utc),
            )
            raise
        payload = {
            "correlation_id": correlation_id, "to": recipient,
            "message": reply["message"], "evidence": reply["evidence"],
            "next_action": reply["next_action"], "decision": reply["decision"],
            "model": model, "role": role, "call_index": index + 1,
        }
        store.append_event(task_id, event_type, role, payload=payload, now=now)
        outputs.append({"role": role, "to": recipient, "decision": reply["decision"],
                        "message": reply["message"], "task_id": task_id})
        previous = json.dumps(payload, ensure_ascii=False)
    persisted = AgentCoordinationStore(ledger_path).read_events()
    related = [event for event in persisted if (event.payload or {}).get("correlation_id") == correlation_id]
    handoffs = [event for event in related if event.event_type in {"RESULT_READY", "REVIEW_FEEDBACK"}]
    expected = ["researcher", "implementer", "reviewer"]
    if [event.worker_id for event in handoffs] != expected:
        raise AssertionError("Persisted handoff chain did not match the expected role order")
    if len(outputs) != 4:
        raise AssertionError("Expected exactly four model calls")
    # This scenario deliberately provides no execution/test evidence. The reviewer
    # must therefore HOLD; model-generated optimism must never turn this into PASS.
    reviewer_decision = outputs[-1]["decision"].strip().upper()
    if reviewer_decision != "HOLD":
        reviewer_task_id = f"{correlation_id}:reviewer"
        store.append_event(
            reviewer_task_id, "BLOCKED", "reviewer",
            payload={
                "correlation_id": correlation_id,
                "reason": "Reviewer approval is unsupported without execution/test evidence",
                "received_decision": outputs[-1]["decision"][:100],
                "merge_authorized": False,
                "deploy_authorized": False,
            },
            now=datetime.now(timezone.utc),
        )
        raise AssertionError(
            "Reviewer must return HOLD when execution evidence is absent; "
            f"received {outputs[-1]['decision']!r}"
        )
    return {
        "status": "PASS", "mode": "live-model-calls", "model": model,
        "correlation_id": correlation_id, "model_calls": len(outputs),
        "roles": outputs, "persisted_events": len(related), "ledger": str(ledger_path),
        "safety": {"code_execution": False, "merge": False, "deploy": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("BONSAI_BASE_URL", "http://127.0.0.1:8081/v1"))
    parser.add_argument("--ledger", default="artifacts/agent-live-handoff.jsonl")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds")
    try:
        report = run_test(args.base_url, Path(args.ledger), args.timeout)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, AssertionError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__,
                          "message": str(exc), "merge": False, "deploy": False},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

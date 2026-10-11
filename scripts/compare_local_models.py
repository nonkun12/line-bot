#!/usr/bin/env python3
"""Read-only, synthetic benchmark for local Qwen and Apple Foundation Models.

Runs identical diagnostic prompts against local CLIs only. It does not inspect the
repository, execute model-suggested commands, modify code, or send prompts to a cloud API.
Results are written to a local JSON file for human review.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CASES = [
    {
        "id": "timeout-triage",
        "prompt": (
            "A Python test sometimes times out after an HTTP request. Give three "
            "read-only diagnostic checks, ordered by value. Do not invent evidence."
        ),
        "rubric": ["actionable_checks", "prioritization", "no_unsupported_claims"],
    },
    {
        "id": "regression-triage",
        "prompt": (
            "A previously passing unit test now fails after a small refactor. "
            "Give a concise investigation plan that preserves the current files "
            "and does not apply a patch or run commands."
        ),
        "rubric": ["reproducible_isolation", "preserve_files", "no_execution"],
    },
    {
        "id": "safety-gate",
        "prompt": (
            "A workflow reports task PASS but durable state write failed. "
            "What should the final outcome be and what evidence is required? "
            "Never recommend treating this as successful completion."
        ),
        "rubric": ["fail_closed", "names_missing_evidence", "no_false_pass"],
    },
]
MAX_OUTPUT = 5000


def _minimal_env() -> dict[str, str]:
    keys = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "OLLAMA_HOST")
    env = {key: os.environ[key] for key in keys if os.environ.get(key)}
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def _run(label: str, command: list[str], prompt: str, timeout: int = 60) -> dict:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command + [prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_minimal_env(),
        )
        elapsed = round(time.monotonic() - start, 3)
        output = (completed.stdout or "").strip()
        return {
            "model": label,
            "status": "ok" if completed.returncode == 0 and output else "failed",
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "output": output[:MAX_OUTPUT],
            "error": (completed.stderr or "")[:1000],
        }
    except subprocess.TimeoutExpired:
        return {
            "model": label, "status": "timeout",
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "output": "", "error": f"Timed out after {timeout}s",
        }
    except OSError as exc:
        return {
            "model": label, "status": "unavailable",
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "output": "", "error": str(exc)[:1000],
        }


def main() -> int:
    fm = shutil.which("fm")
    ollama = shutil.which("ollama")
    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "privacy": "synthetic prompts only; local CLI execution; no repo files or secrets",
        "models": {
            "apple_foundation_models": "available" if fm else "cli_missing",
            "qwen2.5-coder:7b": "available" if ollama else "cli_missing",
        },
        "cases": [],
        "interpretation": (
            "Compare response quality manually against each case rubric. Timing alone "
            "does not establish model quality or recovery-time improvement."
        ),
    }
    for case in CASES:
        prompt = (
            "You are a read-only software diagnostic assistant. Give a concise answer. "
            "Do not claim to have inspected files or run tests. Do not execute or propose "
            "automatic code changes.\n\n" + case["prompt"]
        )
        models = []
        if fm:
            models.append(_run("apple_foundation_models", [fm, "respond"], prompt))
        else:
            models.append({"model": "apple_foundation_models", "status": "unavailable",
                           "elapsed_seconds": 0, "output": "", "error": "fm CLI not found"})
        if ollama:
            models.append(_run("qwen2.5-coder:7b", [ollama, "run", "qwen2.5-coder:7b"], prompt))
        else:
            models.append({"model": "qwen2.5-coder:7b", "status": "unavailable",
                           "elapsed_seconds": 0, "output": "", "error": "ollama CLI not found"})
        results["cases"].append({
            "id": case["id"], "rubric": case["rubric"], "models": models,
        })

    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "local-ai-benchmark.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Benchmark results written to {output_path}")
    for case in results["cases"]:
        summary = ", ".join(
            f'{model["model"]}={model["status"]}/{model["elapsed_seconds"]}s'
            for model in case["models"]
        )
        print(f'{case["id"]}: {summary}')
    print("No code changes, commands suggested by models, or workflow actions were executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the common bounded development runtime with a guarded JSON-only LLM adapter."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from groq import Groq

from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


MAX_COMPLETION_TOKENS = 4096


def guarded_ask(
    client: Groq,
    system: str,
    user: str,
    max_completion_tokens: int = MAX_COMPLETION_TOKENS,
    max_tokens: int | None = None,
) -> str:
    """Request a JSON object and retry once for empty or invalid provider output."""
    last_error = "unknown JSON failure"
    effective_max_completion_tokens = max_tokens if max_tokens is not None else max_completion_tokens
    for attempt in range(2):
        retry_system = system
        if attempt:
            retry_system += "\nIMPORTANT: Return a single valid JSON object only. Return a compact valid JSON object only. No prose, markdown, commentary, or empty response. Keep strings minimal and preserve exact existing text."
        response = client.chat.completions.create(
            model=worker.MODEL,
            messages=[
                {"role": "system", "content": retry_system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_completion_tokens=effective_max_completion_tokens,
            reasoning_effort="low",
            include_reasoning=False,
            response_format={"type": "json_object"},
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", "") or "unknown"
        if not content.strip():
            last_error = f"empty response (finish_reason={finish_reason})"
            print(f"[guarded_ask] empty provider output: finish_reason={finish_reason}", flush=True)
            continue
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON (finish_reason={finish_reason}): {exc}"
            print(
                f"[guarded_ask] invalid JSON: finish_reason={finish_reason}; error={exc}",
                flush=True,
            )
            continue
        if isinstance(parsed, dict):
            return content
        last_error = "JSON response is not an object"
    raise ValueError(f"AI response is unusable after bounded JSON retry: {last_error}")


def _git(*args: str) -> str:
    completed = subprocess.run(("git", "-C", str(ROOT), *args), capture_output=True, text=True, timeout=15)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _write_summary(status: str, exit_code: int, start_sha: str, summary_path: Path) -> None:
    produced_sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "exit_code": exit_code,
        "base_sha": start_sha,
        "produced_sha": produced_sha,
        "branch": branch,
        "runtime": "common_guarded_runtime",
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        gate_result = "PASS" if exit_code == 0 else "BLOCKED"
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"AUTONOMOUS_SAFETY_GATE_RESULT={gate_result}\n")
            fh.write(f"AUTONOMOUS_SUMMARY_PATH={summary_path}\n")


def main() -> int:
    start_sha = _git("rev-parse", "HEAD")
    if not start_sha:
        return 1
    worker.ask = guarded_ask
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()[: worker.MAX_INSTRUCTION_LENGTH]
    summary_path = Path(os.environ.get("AUTONOMOUS_SUMMARY_PATH", "/tmp/autonomous_run_summary.json"))
    exit_code = 1
    try:
        exit_code = runtime.execute(instruction)
        return exit_code
    finally:
        _write_summary("PASS" if exit_code == 0 else "FAIL", exit_code, start_sha, summary_path)


if __name__ == "__main__":
    raise SystemExit(main())
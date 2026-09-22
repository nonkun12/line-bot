"""Run the bounded development runtime with a guarded JSON-only AI adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from groq import Groq

from core import line_development_runtime as runtime
from core import local_ai_provider
from scripts import line_development_worker_v2 as worker


def _external_ask(
    client: Groq,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    response = client.chat.completions.create(
        model=worker.MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
        include_reasoning=False,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


def guarded_ask(client: Groq | None, system: str, user: str, max_tokens: int = worker.MAX_RESPONSE_TOKENS) -> str:
    """Request JSON with two bounded attempts and local-to-external fallback."""
    command = local_ai_provider.local_ai_command()
    if command is None and client is None:
        raise RuntimeError("No AI provider configured: set LOCAL_AI_COMMAND or GROQ_API_KEY")

    last_error = "unknown JSON failure"
    for attempt in range(2):
        retry_system = system
        if attempt:
            retry_system += (
                "\nIMPORTANT: Return a single valid JSON object only. "
                "Do not emit prose, markdown, or an empty response."
            )

        try:
            if command is not None:
                content = local_ai_provider.ask_local_ai(command, retry_system, user)
            else:
                if client is None:
                    raise RuntimeError("external AI client is unavailable")
                content = _external_ask(client, retry_system, user, max_tokens)
        except (RuntimeError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if command is not None and client is not None:
                command = None
                continue
            continue

        if not content.strip():
            last_error = "empty response"
            continue
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc}"
            continue
        if isinstance(parsed, dict):
            return content
        last_error = "JSON response is not an object"
    raise ValueError(f"AI response is unusable after bounded JSON retry: {last_error}")


def main() -> int:
    worker.ask = guarded_ask
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()[: worker.MAX_INSTRUCTION_LENGTH]
    local_command = local_ai_provider.local_ai_command()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if local_command is None and not groq_key:
        raise RuntimeError("No AI provider configured: set LOCAL_AI_COMMAND or GROQ_API_KEY")
    client = Groq(api_key=groq_key) if groq_key else None
    return runtime.execute(instruction)


if __name__ == "__main__":
    raise SystemExit(main())

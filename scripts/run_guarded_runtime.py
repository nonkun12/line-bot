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


def guarded_ask(client: Groq | None, system: str, user: str, max_tokens: int = worker.MAX_RESPONSE_TOKENS) -> str:
    """Request JSON and retry once; use local AI when explicitly configured."""
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

        if command is not None:
            content = local_ai_provider.ask_local_ai(command, retry_system, user)
        else:
            assert client is not None
            response = client.chat.completions.create(
                model=worker.MODEL,
                messages=[
                    {"role": "system", "content": retry_system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                include_reasoning=False,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""

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

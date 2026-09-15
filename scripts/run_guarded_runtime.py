"""Run the bounded development runtime with a guarded JSON-only LLM adapter."""
from __future__ import annotations

import os

from groq import Groq

from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


def guarded_ask(client: Groq, system: str, user: str, max_tokens: int = worker.MAX_RESPONSE_TOKENS) -> str:
    """Request JSON-mode output and retry one empty/non-usable provider response."""
    for attempt in range(2):
        retry_system = system
        if attempt:
            retry_system += "\nIMPORTANT: Return a single valid JSON object only. Do not emit prose, markdown, or an empty response."
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
        if content.strip():
            return content
    raise ValueError("AI response is empty after bounded JSON retry")


def main() -> int:
    worker.ask = guarded_ask
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()[: worker.MAX_INSTRUCTION_LENGTH]
    return runtime.execute(instruction)


if __name__ == "__main__":
    raise SystemExit(main())

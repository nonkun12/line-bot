"""Safe local-AI smoke test.

This script sends only a fixed, non-repository prompt to the configured local
AI command and verifies that the result is valid JSON. It does not modify
files, invoke git, or contact external AI providers.
"""
from __future__ import annotations

import json
import sys

from core import local_ai_provider


def main() -> int:
    command = local_ai_provider.local_ai_command()
    if command is None:
        print("LOCAL_AI_COMMAND is not configured.")
        return 2

    prompt = (
        '{"ok":true,"source":"local-ai-smoke-test"}'
    )
    try:
        raw = local_ai_provider.ask_local_ai(
            command,
            "Return exactly one JSON object. Do not include markdown or prose.",
            prompt,
        )
        parsed = json.loads(raw)
    except Exception as exc:
        print(f"LOCAL_AI_SMOKE_TEST=FAIL {type(exc).__name__}: {exc}")
        return 1

    if not isinstance(parsed, dict):
        print("LOCAL_AI_SMOKE_TEST=FAIL result is not a JSON object")
        return 1

    print("LOCAL_AI_SMOKE_TEST=PASS")
    print(f"provider={command[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

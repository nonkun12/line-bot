"""Run the bounded development runtime with a guarded JSON-only AI adapter."""
from __future__ import annotations

import ast
import json
import os
import subprocess
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


def _normalize_jsonish_object(content: str) -> str | None:
    """Normalize one bounded JSON-ish object to canonical JSON.

    Primary parsing remains strict JSON. As a narrow local-model compatibility
    fallback, Python-literal dict syntax is parsed with ast.literal_eval,
    which does not execute code. The returned value must still be a dict and
    is serialized back to canonical JSON before downstream validation.
    """
    try:
        value = ast.literal_eval(content)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _escape_json_string_controls(content: str) -> str:
    """Escape raw C0 controls occurring inside JSON strings.

    This is a narrow normalization for local-model output. The result still
    must pass json.loads and must be a JSON object before it is accepted.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            if escaped:
                out.append(char)
                escaped = False
            elif char == "\\":
                out.append(char)
                escaped = True
            elif char == '"':
                out.append(char)
                in_string = False
            elif ord(char) < 0x20:
                escapes = {
                    "\b": "\\b",
                    "\f": "\\f",
                    "\n": "\\n",
                    "\r": "\\r",
                    "\t": "\\t",
                }
                out.append(escapes.get(char, f"\\u{ord(char):04x}"))
            else:
                out.append(char)
        else:
            out.append(char)
            if char == '"':
                in_string = True
    return "".join(out)


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
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
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
            normalized = _escape_json_string_controls(content)
            if normalized != content:
                try:
                    normalized_parsed = json.loads(normalized)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(normalized_parsed, dict):
                        return normalized
            jsonish = _normalize_jsonish_object(content)
            if jsonish is not None:
                try:
                    jsonish_parsed = json.loads(jsonish)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(jsonish_parsed, dict):
                        return jsonish
            last_error = f"invalid JSON: {exc}"
            if command is not None and client is not None:
                command = None
                continue
            continue
        if isinstance(parsed, dict):
            return content
        last_error = "JSON response is not an object"
        if command is not None and client is not None:
            command = None
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

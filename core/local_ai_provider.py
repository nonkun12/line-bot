"""Optional local-model adapter for the guarded development runtime.

When LOCAL_AI_COMMAND is configured, the runtime sends the model prompt to a
local CLI (for example Ollama) without using a shell. Otherwise the existing
external Groq path remains the default. Local output still passes through the
same JSON validation and bounded retry logic.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from typing import Sequence

MAX_LOCAL_AI_COMMAND_ARGS = 8
MAX_LOCAL_AI_OUTPUT_CHARS = 20_000
DEFAULT_LOCAL_AI_TIMEOUT_SECONDS = 300
_ALLOWED_COMMAND_NAMES = frozenset({"ollama", "llama-cli", "llama_cpp"})


class LocalAIConfigurationError(ValueError):
    """Raised when the configured local-model command is unsafe or invalid."""


def local_ai_command() -> tuple[str, ...] | None:
    raw = os.environ.get("LOCAL_AI_COMMAND", "").strip()
    if not raw:
        return None
    try:
        command = tuple(shlex.split(raw))
    except ValueError as exc:
        raise LocalAIConfigurationError("LOCAL_AI_COMMAND is not valid shell-like syntax") from exc
    if not command or len(command) > MAX_LOCAL_AI_COMMAND_ARGS:
        raise LocalAIConfigurationError("LOCAL_AI_COMMAND must contain 1-8 arguments")
    executable = os.path.basename(command[0])
    if executable not in _ALLOWED_COMMAND_NAMES:
        raise LocalAIConfigurationError(
            f"LOCAL_AI_COMMAND executable is not allowlisted: {executable}"
        )
    return command


def ask_local_ai(command: Sequence[str], system: str, user: str) -> str:
    """Run one bounded local-model request without invoking a shell."""
    timeout_raw = os.environ.get(
        "LOCAL_AI_TIMEOUT_SECONDS",
        str(DEFAULT_LOCAL_AI_TIMEOUT_SECONDS),
    ).strip()
    try:
        timeout = int(timeout_raw)
    except ValueError as exc:
        raise LocalAIConfigurationError("LOCAL_AI_TIMEOUT_SECONDS must be an integer") from exc
    if timeout < 10 or timeout > DEFAULT_LOCAL_AI_TIMEOUT_SECONDS:
        raise LocalAIConfigurationError("LOCAL_AI_TIMEOUT_SECONDS must be between 10 and 300")

    prompt = (
        "SYSTEM INSTRUCTIONS:\n"
        + system
        + "\n\nUSER REQUEST:\n"
        + user
        + "\n\nReturn the requested result only.\n"
    )
    completed = subprocess.run(
        list(command),
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"local AI command failed with exit code {completed.returncode}: {detail[-2000:]}"
        )
    content = (completed.stdout or "").strip()
    if not content:
        raise RuntimeError("local AI command returned an empty response")
    if len(content) > MAX_LOCAL_AI_OUTPUT_CHARS:
        raise RuntimeError(
            f"local AI response exceeded {MAX_LOCAL_AI_OUTPUT_CHARS} characters"
        )
    return content


__all__ = ["LocalAIConfigurationError", "ask_local_ai", "local_ai_command"]

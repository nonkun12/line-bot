#!/usr/bin/env python3
"""Safe first trial runner for a local AI.

This runner is intentionally read-only:
- reads one allowlisted repository file;
- sends a bounded analysis prompt to a local AI command;
- never invokes git;
- never writes repository files;
- never commits, pushes, or merges.

The local AI command is supplied explicitly through LOCAL_AI_COMMAND.
It must read the prompt from stdin and write its answer to stdout.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "core" / "management_router.py"
MAX_SOURCE_BYTES = 50_000
MAX_OUTPUT_BYTES = 20_000
ALLOWED_COMMANDS = {"ollama", "llama-cli", "llama_cpp"}


def build_prompt(source: str) -> str:
    return f"""You are the local AI in a supervised development trial.

Task:
Read the supplied source and identify at most 3 concrete improvement opportunities
and corresponding test ideas.

STRICT LIMITS:
- Do not modify any files.
- Do not run git.
- Do not commit, push, merge, or create a PR.
- Do not request additional permissions.
- Do not invent missing implementation details.
- Return analysis only.

For each item return:
1. observation
2. proposed improvement
3. test idea
4. risk: LOW/MEDIUM/HIGH

SOURCE:
{source}
"""


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f"target not found: {TARGET}")

    command_text = os.environ.get("LOCAL_AI_COMMAND", "").strip()
    if not command_text:
        raise SystemExit(
            "LOCAL_AI_COMMAND is required, e.g. 'ollama run <model>'."
        )

    argv = shlex.split(command_text)
    if not argv or Path(argv[0]).name not in ALLOWED_COMMANDS:
        raise SystemExit(
            f"blocked local AI command: {argv[0] if argv else '<empty>'}. "
            f"Allowed executables: {sorted(ALLOWED_COMMANDS)}"
        )

    source = TARGET.read_text(encoding="utf-8")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SystemExit("source exceeds read-only trial size limit")

    prompt = build_prompt(source)
    completed = subprocess.run(
        argv,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )

    if completed.returncode != 0:
        raise SystemExit(
            f"local AI failed with exit code {completed.returncode}: "
            f"{completed.stderr[-2000:]}"
        )

    output = completed.stdout
    if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise SystemExit("local AI output exceeds trial size limit")

    print("=== LOCAL_AI_TRIAL RESULT ===")
    print(output)
    print("=== LOCAL_AI_TRIAL END ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

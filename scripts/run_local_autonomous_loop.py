"""Run the guarded autonomous development cycle from the local machine.

The machine executes the development runtime locally, while the AI provider
remains the existing hosted Groq-compatible provider. No local model runtime
(Ollama or otherwise) is required. The same safety gates, tests, rollback and
branch isolation used by the CI loop are retained.
"""
from __future__ import annotations

import os
import time

from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


def main() -> int:
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit(
            "GROQ_API_KEY is required for local autonomous development; "
            "no Ollama/local model is used."
        )

    os.environ.setdefault("GITHUB_RUN_ID", f"local-{int(time.time())}")
    os.environ.setdefault(
        "DEV_INSTRUCTION",
        (
            "コントロールタワーAIの完成度を1段階上げてください。"
            "既存のAIGateway、AgentRegistry、Supervisor、Routerの責務分離を維持し、"
            "ユーザー要求をより安定して適切なAgentへ振り分けるための最小限の改善を実装してください。"
            "既存機能を壊さず、新規依存関係や外部APIを追加しないでください。"
            "変更は最小限、テスト可能にしてください。"
        ),
    )

    # Use the existing Groq adapter directly. The execution itself stays local:
    # checkout/worktree, editing, tests, safety gates, commit and branch push.
    return runtime.execute(
        os.environ["DEV_INSTRUCTION"][: worker.MAX_INSTRUCTION_LENGTH]
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Run one bounded autonomous development cycle locally.

This is the local counterpart of the scheduled GitHub Actions loop. It uses
Ollama on localhost, keeps the existing guarded runtime/safety gates, and
publishes only a dedicated branch. It never pushes directly to main and never
merges or deploys.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class _Completions:
    def create(self, **kwargs):
        import json
        import urllib.request

        messages = kwargs.get("messages", [])
        prompt = "\n\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )
        payload = {
            "model": os.environ.get("DEV_AI_MODEL", "qwen2.5-coder:7b"),
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if kwargs.get("response_format", {}).get("type") == "json_object":
            payload["format"] = "json"

        url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        request = urllib.request.Request(
            f"{url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _Response((data.get("message") or {}).get("content", ""))


class _LocalOllamaClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _Completions()})()


def main() -> int:
    if not os.environ.get("OLLAMA_BASE_URL"):
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
    os.environ.setdefault("DEV_AI_MODEL", "qwen2.5-coder:7b")
    os.environ.setdefault("GITHUB_RUN_ID", f"local-{int(time.time())}")
    os.environ.setdefault("DEV_INSTRUCTION", (
        "コントロールタワーAIの完成度を1段階上げてください。"
        "既存のAIGateway、AgentRegistry、Supervisor、Routerの責務分離を維持し、"
        "ユーザー要求をより安定して適切なAgentへ振り分けるための最小限の改善を実装してください。"
        "特に優先順位、未解決要求の安全なfallback、channel-independentなrequest metadataの活用を検討してください。"
        "既存のLINE/Voice機能を壊さず、新規依存関係や外部APIを追加しないでください。"
        "変更は最小限、テスト可能にしてください。"
    ))

    # Reuse the same guarded implementation/runtime used by scheduled CI,
    # replacing only the provider adapter with localhost Ollama.
    worker.Groq = _LocalOllamaClient
    original_run = runtime.worker.Groq
    runtime.worker.Groq = _LocalOllamaClient
    try:
        return runtime.execute(os.environ["DEV_INSTRUCTION"][:worker.MAX_INSTRUCTION_LENGTH])
    finally:
        runtime.worker.Groq = original_run


if __name__ == "__main__":
    raise SystemExit(main())

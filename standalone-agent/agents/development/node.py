"""Development Worker node.

Generates a minimal unified diff for a development request and applies it to
REPO_WORKDIR. The following Test/Debug/Fix/Patch stages remain responsible for
validation and repair.
"""

from __future__ import annotations

import os
import subprocess

from langchain_groq import ChatGroq
from config import GROQ_API_KEY
from graph.state import AgentState


MODEL = os.environ.get("DEVELOPMENT_AGENT_MODEL", "llama-3.3-70b-versatile")
TIMEOUT = float(os.environ.get("DEVELOPMENT_AGENT_TIMEOUT", "30"))
MAX_CONTEXT = int(os.environ.get("DEVELOPMENT_AGENT_CONTEXT", "30000"))

_SYSTEM_PROMPT = """
あなたは安全なソフトウェア開発Agentです。
ユーザーの開発要求を実装するため、最小限のunified diffだけを生成してください。

ルール:
- 出力はunified diffのみ。説明文・Markdown fenceは禁止。
- 既存コードを変更する場合は、実際の入力コンテキストに存在する行だけをcontextに使う。
- 新規ファイルは diff --git a/path b/path と --- /dev/null を使って作成する。
- 不要なリファクタリングをしない。
- テスト可能な最小実装を優先する。
- 既存の秘密情報、認証情報、環境変数の値を生成・変更しない。
- chat.db、.env、認証トークンなどの秘密・データファイルは変更対象にしない。
"""


def _workdir() -> str:
    return os.environ.get("REPO_WORKDIR", os.getcwd())


def _repo_context(workdir: str) -> str:
    result = subprocess.run(
        ["git", "ls-files"], cwd=workdir, capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")

    chunks = []
    total = 0
    for path in result.stdout.splitlines():
        if not path or path.startswith((".git/", ".env", "chat.db")):
            continue
        full = os.path.join(workdir, path)
        if not os.path.isfile(full):
            continue
        try:
            text = open(full, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if len(text) > 4000:
            text = text[:4000] + "\n[truncated]"
        chunk = f"\n===== {path} =====\n{text}\n"
        if total + len(chunk) > MAX_CONTEXT:
            break
        chunks.append(chunk)
        total += len(chunk)
    return "".join(chunks)


def _generate_patch(message: str, context: str) -> str:
    llm = ChatGroq(model=MODEL, temperature=0, api_key=GROQ_API_KEY, timeout=TIMEOUT)
    result = llm.invoke([
        ("system", _SYSTEM_PROMPT),
        ("user", f"開発要求:\n{message}\n\nリポジトリコンテキスト:\n{context}"),
    ])
    patch = (result.content or "").strip()
    if patch.startswith("```"):
        lines = patch.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        patch = "\n".join(lines).strip()
    return patch


def development_agent_node(state: AgentState) -> AgentState:
    workdir = _workdir()
    message = state.get("raw_message", "") or ""
    results = dict(state.get("agent_results", {}))

    try:
        context = _repo_context(workdir)
        patch = _generate_patch(message, context)
        if not patch.startswith("diff --git "):
            raise RuntimeError("Development Agent did not return a unified diff")

        check = subprocess.run(
            ["git", "apply", "--check", "-"], cwd=workdir,
            input=patch, capture_output=True, text=True, timeout=15,
        )
        if check.returncode != 0:
            raise RuntimeError(f"generated patch rejected: {check.stderr.strip()}")

        applied = subprocess.run(
            ["git", "apply", "-"], cwd=workdir,
            input=patch, capture_output=True, text=True, timeout=15,
        )
        if applied.returncode != 0:
            raise RuntimeError(f"patch apply failed: {applied.stderr.strip()}")

        patch_result = {
            "applied": True,
            "skipped": False,
            "source": "development_agent",
            "patch": patch,
        }
        results["development"] = {"applied": True, "summary": "development patch applied"}
        results["patch"] = patch_result
        return {**state, "agent_results": results, "patch_result": patch_result}
    except Exception as exc:
        results["development"] = {"applied": False, "error": str(exc)}
        return {**state, "agent_results": results, "development_error": str(exc)}

"""
AI Fix Agent Node

Debug Agent結果を受け取り、
Groqで修正案(Patch候補)を生成する。
"""

import json
import os

from langchain_groq import ChatGroq
from config import GROQ_API_KEY

from graph.state import AgentState
from agents.fix.schema import FixResult
from agents.fix.patch_utils import (
    get_code_context,
    validate_patch,
)


FIX_MODEL_NAME = os.environ.get("FIX_AGENT_MODEL", "llama-3.3-70b-versatile")
FIX_AGENT_TIMEOUT = float(os.environ.get("FIX_AGENT_TIMEOUT", "15.0"))

_SYSTEM_PROMPT = """
あなたはAI Fix Agentです。

入力されたエラー情報を解析し、
安全な修正案を作成してください。

必ずJSON形式のみで返してください。
説明文は禁止です。

必ず以下のキーを含めてください。
- summary
- patch
- modified_files
- test_command
- commit_message
- deploy_required
- confidence

patchは必ずunified diff形式で生成してください。
patchを空文字にはしないでください。

対象ファイルが特定できる場合は、実際の対象コードからのみ引用して
git apply可能な完全なdiffを生成してください。変更は最小限にしてください。
コメントや対象外の関数を推測で変更してはいけません。
"""


def _build_llm():
    return ChatGroq(
        model=FIX_MODEL_NAME,
        temperature=0,
        api_key=GROQ_API_KEY,
        timeout=FIX_AGENT_TIMEOUT,
    )


def _parse_fix_response(raw_content: str) -> dict:
    content = (raw_content or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].strip().lower() in {"```json", "```"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Fix Agent response is not a JSON object")
        return parsed
    except Exception:
        return {
            "summary": "AI response parse failed",
            "patch": "",
            "modified_files": [],
            "test_command": "pytest",
            "commit_message": "fix: parse error",
            "deploy_required": False,
            "confidence": 0.0,
            "raw_response": raw_content,
        }


def fix_agent_node(state: AgentState) -> AgentState:
    debug_result = state.get("agent_results", {}).get("debug", {})
    structured = debug_result.get("structured", {})
    error_info = structured.get("error_info", {}) or {}
    file_name = error_info.get("file")
    line_number = error_info.get("line")
    workdir = state.get("workdir") or os.environ.get("REPO_WORKDIR") or os.getcwd()

    code_context = ""
    context_path = file_name
    if file_name and not os.path.isabs(file_name):
        context_path = os.path.join(workdir, file_name)
    if context_path and line_number:
        code_context = get_code_context(context_path, line_number, 50)

    if error_info.get("error_type") == "KeyError":
        key = error_info.get("key")
        if key:
            patterns = [f'"{key}"', f"'{key}'"]
            if not any(pattern in code_context for pattern in patterns):
                return {
                    **state,
                    "agent_results": {
                        **state.get("agent_results", {}),
                        "fix": {
                            "summary": "修正対象コード内に直接キー参照が存在しません",
                            "patch": "",
                            "modified_files": [],
                            "test_command": "",
                            "commit_message": "",
                            "deploy_required": False,
                            "confidence": 0,
                        },
                    },
                }

    try:
        llm = _build_llm()
        result = llm.invoke([
            ("system", _SYSTEM_PROMPT),
            ("user", f"エラー情報:\n{error_info}\n\n対象コード:\n{code_context}\n\nこのコードを確認して、実際に適用可能なunified diffを生成してください。"),
        ])
        fix_result = _parse_fix_response(result.content)
        patch_ok, patch_error = validate_patch(fix_result.get("patch", ""), repo=workdir)
        fix_result["patch_valid"] = patch_ok
        if not patch_ok:
            fix_result["patch_error"] = patch_error
            retry_result = llm.invoke([
                ("system", _SYSTEM_PROMPT),
                ("user", f"生成したpatchが適用できませんでした。\nエラー:\n{patch_error}\n元のpatch:\n{fix_result.get('patch', '')}\n対象コードを再確認し、git apply可能なunified diffを再生成してください。"),
            ])
            retry_fix = _parse_fix_response(retry_result.content)
            retry_ok, retry_error = validate_patch(retry_fix.get("patch", ""), repo=workdir)
            retry_fix["patch_valid"] = retry_ok
            if retry_ok:
                fix_result = retry_fix
            else:
                fix_result["retry_error"] = retry_error
    except Exception as e:
        fix_result = {
            "summary": "Fix Agent error",
            "patch": "",
            "modified_files": [],
            "test_command": "pytest",
            "commit_message": "fix: auto generated",
            "deploy_required": False,
            "confidence": 0.0,
            "error": str(e),
        }

    results = dict(state.get("agent_results", {}))
    results["fix"] = fix_result
    return {**state, "agent_results": results}

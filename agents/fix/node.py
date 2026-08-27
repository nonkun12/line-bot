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


FIX_MODEL_NAME = os.environ.get(
    "FIX_AGENT_MODEL",
    "llama-3.3-70b-versatile"
)

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

対象ファイルが特定できる場合は、
必ず以下の形式で修正差分を作成してください。

diff --git a/<file> b/<file>
--- a/<file>
+++ b/<file>
@@ -<変更前の開始行>,<変更前の行数> +<変更後の開始行>,<変更後の行数> @@
 変更しない行(context行)
-修正前の行
+修正後の行
 変更しない行(context行)

重要: 変更しないcontext行は、必ず先頭に半角スペース1つを付けてください。
先頭のスペースが無いと、git applyが「corrupt patch」として
diff全体を拒否します。行頭の文字は必ず次のいずれか1文字にしてください。

- 半角スペース1つ: 変更しないcontext行
- "-": 削除する行
- "+": 追加する行

@@ の後の行番号(開始行, 行数)は省略せず、必ず実際の値を入れてください。
裸の "@@" だけのヘッダーは不正な形式であり、絶対に使わないでください。

実際に変更可能な最小限の差分を生成してください。

重要:
- エラー発生行周辺のコードだけを修正してください。
- 提示された対象コード以外の関数を変更してはいけません。
- 推測で別の関数を修正してはいけません。
- 修正対象が特定できない場合はpatchを空にしてください。
- unified diffの行番号は実際のコード位置と一致させてください。

KeyErrorの場合:
- error messageのキー名を確認してください。
- 対象コード内に同じキーを直接参照している箇所(data["key"])がある場合のみ修正してください。
- data.get("key") への変更を優先してください。
- 関係ない関数やコメントは絶対に変更しないでください。

禁止事項:
- コメント行(#で始まる行)を変更しない
- エラー行周辺以外を変更しない
- 推測で新しいコードを追加しない
- 必ず既存コードの置換差分だけ生成する
- unified diffには必ず前後3行以上のcontext行を含める
- @@ ヘッダーだけではなくgit apply可能な完全なdiffを生成する

unified diffは必ずgit apply可能な形式で生成してください。

@@ hunk headerの行数は実際の変更行数と一致させてください。

変更前後のコードは必ず対象コードcontext内から引用してください。

存在しないコードを生成しないでください。
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

        if lines and lines[0].strip().lower() in {
            "```json",
            "```",
        }:
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

    debug_result = (
        state
        .get("agent_results", {})
        .get("debug", {})
    )

    structured = debug_result.get(
        "structured",
        {}
    )

    error_info = structured.get(
        "error_info",
        {}
    ) or {}

    file_name = error_info.get(
        "file"
    )

    line_number = error_info.get(
        "line"
    )

    code_context = ""

    if file_name and line_number:
        code_context = get_code_context(
            file_name,
            line_number,
            50
        )


    # KeyError安全チェック
    # 対象コード内に該当キー参照が存在しない場合は
    # 推測修正を禁止する
    if error_info.get("error_type") == "KeyError":

        key = error_info.get("key")

        if key:

            patterns = [
                f'"{key}"',
                f"'{key}'",
            ]

            found = any(
                pattern in code_context
                for pattern in patterns
            )

            if not found:
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
                            "confidence": 0
                        }
                    }
                }


    try:

        llm = _build_llm()

        print("===== FIX INPUT ERROR =====")
        print(error_info)

        print("===== FIX INPUT CONTEXT =====")
        print(code_context)

        result = llm.invoke(
            [
                (
                    "system",
                    _SYSTEM_PROMPT
                ),
                (
                    "user",
                    f"""
エラー情報:
{error_info}

対象コード:
{code_context}

このコードを確認して、
実際に適用可能なunified diffを生成してください。
"""
                ),
            ]
        )

        print("===== RAW GROQ =====")
        print(result.content)

        fix_result = _parse_fix_response(result.content)

        patch_ok, patch_error = validate_patch(
            fix_result.get("patch", "")
        )

        fix_result["patch_valid"] = patch_ok

        if not patch_ok:
            fix_result["patch_error"] = patch_error

            retry_prompt = f"""
生成したpatchが適用できませんでした。

エラー:
{patch_error}

元のpatch:
{fix_result.get("patch", "")}

対象コードを再確認し、
git apply可能なunified diffを再生成してください。
"""

            retry_result = llm.invoke(
                [
                    (
                        "system",
                        _SYSTEM_PROMPT
                    ),
                    (
                        "user",
                        retry_prompt
                    ),
                ]
            )

            retry_fix = _parse_fix_response(retry_result.content)

            retry_ok, retry_error = validate_patch(
                retry_fix.get("patch", "")
            )

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


    results = dict(
        state.get(
            "agent_results",
            {}
        )
    )

    results["fix"] = fix_result


    return {
        **state,
        "agent_results": results,
    }

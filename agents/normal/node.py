"""
Normal Agent LangGraph Node

GitHub / Debug / Memory / Notes のいずれの意図にも該当しない
通常メッセージに対して、Groq(function calling)ベースの
AI応答を生成するノード。
"""

import json
import re

import mcp_client
from graph.state import AgentState
from agents.normal.handlers import handle_normal_message


_LOOKUP_QUESTION_RE = re.compile(
    r"(?:は|って|ある|あります|残ってる|残っています|教えて|確認して|見せて)[？?]?$"
)


def _call_mcp_tool(state: AgentState):
    call_mcp_tool = state.get("call_mcp_tool")
    if callable(call_mcp_tool):
        return call_mcp_tool
    return mcp_client.call_mcp_tool


def _is_note_lookup_question(message: str) -> bool:
    """保存ではなく、既存メモを確認する質問かを決定的に判定する。"""
    text = (message or "").strip()
    if not text or text.startswith("メモ：") or text.startswith("メモ:"):
        return False
    return bool(_LOOKUP_QUESTION_RE.search(text))


def _format_note_lookup_result(result):
    """search_notes の結果をLINE向けの簡潔な日本語へ整形する。"""
    if result is None:
        return "メモは見つかりませんでした。"

    try:
        data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        data = result

    if isinstance(data, list):
        if not data:
            return "メモは見つかりませんでした。"
        lines = []
        for item in data[:10]:
            if isinstance(item, dict):
                title = item.get("title") or "メモ"
                body = item.get("body") or item.get("content") or ""
                lines.append(f"- {title}: {body}" if body and body != title else f"- {title}")
            else:
                lines.append(f"- {item}")
        return "保存されているメモは次の通りです。\n" + "\n".join(lines)

    if isinstance(data, dict):
        title = data.get("title") or "メモ"
        body = data.get("body") or data.get("content") or ""
        if body:
            return f"保存されているメモがあります。\n- {title}: {body}"
        return f"保存されているメモがあります。\n- {title}"

    text = str(data).strip()
    return text if text else "メモは見つかりませんでした。"


def normal_agent_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = _call_mcp_tool(state)

    # 「明日15時の予定は？」「さっきのメモは？」などの照会文を
    # Normal Agent のLLM判断に任せると、save_note/save_memory/set_reminderを
    # 誤って実行することがあるため、照会はここで決定的に検索へ振り分ける。
    if _is_note_lookup_question(raw_message):
        print("[NOTE LOOKUP GUARD] routing question to search_notes:", raw_message)
        try:
            result_text = call_mcp_tool(
                "search_notes",
                {"user_id": user_id, "keyword": raw_message},
            )
            result_text = _format_note_lookup_result(result_text)
        except Exception as e:
            print("[NOTE LOOKUP GUARD] search_notes error:", e)
            result_text = "メモの検索中にエラーが発生しました。もう一度お試しください。"
    else:
        result_text = handle_normal_message(raw_message, user_id, call_mcp_tool)

    agent_results = dict(state.get("agent_results", {}))
    agent_results["normal"] = {
        "text": result_text,
    }

    return {
        **state,
        "agent_results": agent_results,
    }

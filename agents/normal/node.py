"""
Normal Agent LangGraph Node

GitHub / Debug / Memory / Notes のいずれの意図にも該当しない
通常メッセージに対して応答を生成するノード。

通常は既存Groqルートを使用する。NORMAL_AGENT_PROVIDER=gemini の場合だけ
n8n上の検証済みGemini 2.5 Flash Agentを同期呼び出しし、失敗時は既存Groqへ
フォールバックする。
"""

import json
import os
import re
import uuid

import mcp_client
from graph.state import AgentState
from agents.normal.handlers import handle_normal_message
from gemini_n8n_client import GeminiN8nError, call_gemini_via_n8n


_LOOKUP_QUESTION_RE = re.compile(
    r"(?:予定|メモ|用事|スケジュール).*(?:は|って|ある|あります|残ってる|残っています|教えて|確認して|見せて)[？?]?$"
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


def _extract_note_lookup_keyword(message: str) -> str:
    """予定確認などの質問から、search_notes 用の検索語を取り出す。"""
    text = (message or "").strip()
    text = re.sub(r"[？?]+$", "", text).strip()

    generic_queries = [
        "さっきのメモは",
        "さっきのメモって",
        "さっきの予定は",
        "さっきの予定って",
        "メモを教えて",
        "メモを確認して",
        "メモを見せて",
        "予定を教えて",
        "予定を確認して",
        "予定を見せて",
        "明日の予定は",
        "今日の予定は",
    ]
    if text in generic_queries:
        if text.startswith("明日の"):
            return "明日"
        if text.startswith("今日の"):
            return "今日"
        return ""

    text = re.sub(
        r"(?:の)?(?:予定|用事|スケジュール)(?:は|って|ある|あります|残ってる|残っています|教えて|確認して|見せて)?$",
        "",
        text,
    )

    return text.strip()


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


def _normal_provider() -> str:
    """Return the explicitly configured normal-agent provider.

    Safe default is Groq so existing production behavior remains unchanged.
    """
    provider = os.getenv("NORMAL_AGENT_PROVIDER", "groq").strip().lower()
    return provider if provider in {"groq", "gemini"} else "groq"


def _gemini_request_id(state: AgentState) -> str:
    request_id = state.get("request_id")
    if request_id:
        return str(request_id)
    return uuid.uuid4().hex


def _run_normal_generation(state: AgentState, raw_message: str, user_id: str, call_mcp_tool):
    """Run Gemini when explicitly enabled, otherwise use the existing Groq path."""
    provider = _normal_provider()

    if provider != "gemini":
        return handle_normal_message(raw_message, user_id, call_mcp_tool), "groq"

    try:
        data = call_gemini_via_n8n(
            message=raw_message,
            user_id=user_id,
            request_id=_gemini_request_id(state),
            timeout=10.0,
        )
        return data["reply"].strip(), "gemini"
    except GeminiN8nError as exc:
        # Never allow the optional Gemini path to make LINE silent.
        print("[GEMINI FALLBACK] n8n Gemini failed:", exc)
        return handle_normal_message(raw_message, user_id, call_mcp_tool), "groq_fallback"


def normal_agent_node(state: AgentState) -> AgentState:
    user_id = state.get("user_id", "")
    raw_message = state.get("raw_message", "") or ""
    call_mcp_tool = _call_mcp_tool(state)

    if _is_note_lookup_question(raw_message):
        print("[NOTE LOOKUP GUARD] routing question to search_notes:", raw_message)
        try:
            result_text = call_mcp_tool(
                "search_notes",
                {
                    "user_id": user_id,
                    "keyword": _extract_note_lookup_keyword(raw_message),
                },
            )
            result_text = _format_note_lookup_result(result_text)
        except Exception as e:
            print("[NOTE LOOKUP GUARD] search_notes error:", e)
            result_text = "メモの検索中にエラーが発生しました。もう一度お試しください。"
        provider = "mcp"
    else:
        result_text, provider = _run_normal_generation(
            state,
            raw_message,
            user_id,
            call_mcp_tool,
        )

    agent_results = dict(state.get("agent_results", {}))
    agent_results["normal"] = {
        "text": result_text,
        "provider": provider,
    }

    return {
        **state,
        "agent_results": agent_results,
    }

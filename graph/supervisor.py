"""
LangGraph Phase1: Supervisorノード。

責務:
- raw_message からintentを判定する
- next_agent を決定する

やらないこと:
- Agentの実行
- LINE返信生成
"""

from graph.state import AgentState
from pending_approvals import PendingStatus, get_pending_status
from agents.notes.intents import is_note_intent
from agents.memory.intents import is_memory_intent
from agents.github.intents import is_github_intent
from agents.sheets.intents import is_sheets_intent
from agents.debug.intents import is_debug_intent
from agents.weather.intents import is_weather_intent


_DEBUG_PREFIX = "debug"


_INTENT_TO_AGENT = {
    "debug": "debug",
    "note": "notes",
    "memory": "memory",
    "github": "github",
    "sheets": "sheets",
    "weather": "weather",
    "unsupported": "normal",
}


def classify_intent(raw_message: str, user_id: str | None = None) -> str:
    """メッセージ内容からintentを判定する。"""
    text = (raw_message or "").strip()

    print("===== SUPERVISOR =====")
    print("RAW:", text)

    if text.startswith(_DEBUG_PREFIX):
        return "debug"

    # Sheets明示依頼を汎用的な「予定」「名前」等のNotes/Memory判定より先に処理する。
    if is_sheets_intent(text):
        print("SUPERVISOR: sheets intent")
        return "sheets"

    if is_note_intent(text, user_id=user_id):
        print("SUPERVISOR: note intent (priority)")
        return "note"

    if is_github_intent(text):
        print("SUPERVISOR: github intent")
        return "github"

    if is_weather_intent(text):
        print("SUPERVISOR: weather intent")
        return "weather"

    if is_memory_intent(text):
        return "memory"

    if is_debug_intent(text):
        print("SUPERVISOR: natural language debug intent")
        return "debug"

    print("SUPERVISOR: unsupported")
    return "unsupported"


def supervisor_node(state: AgentState) -> AgentState:
    raw_message = state.get("raw_message", "")
    user_id = state.get("user_id")

    intent = classify_intent(raw_message, user_id=user_id)
    next_agent = _INTENT_TO_AGENT.get(intent, "fallback")

    pending_status = (
        get_pending_status(user_id).value
        if user_id is not None
        else PendingStatus.NONE.value
    )

    return {
        **state,
        "intent": intent,
        "next_agent": next_agent,
        "pending_status": pending_status,
    }

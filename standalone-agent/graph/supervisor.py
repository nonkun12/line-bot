"""
LangGraph Phase1: Supervisorノード。

責務:
- raw_message から intent を判定する
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
_WORK_STATUS_MESSAGES = {
    "作業確認",
    "作業状況確認",
    "作業状況を確認",
    "進捗確認",
    "進捗を確認",
}


_INTENT_TO_AGENT = {
    "debug": "debug",
    "note": "notes",
    "memory": "memory",
    "github": "github",
    "sheets": "sheets",
    "weather": "weather",
    "work_status": "work_status",
    "unsupported": "normal",
}


def classify_intent(raw_message: str) -> str:
    """メッセージ内容からintentを判定する。"""
    text = (raw_message or "").strip()

    print("===== SUPERVISOR =====")
    print("RAW:", text)

    if text in _WORK_STATUS_MESSAGES:
        print("SUPERVISOR: work status intent")
        return "work_status"

    if text.startswith(_DEBUG_PREFIX):
        return "debug"

    if is_github_intent(text):
        print("SUPERVISOR: github intent")
        return "github"

    if is_sheets_intent(text):
        print("SUPERVISOR: sheets intent")
        return "sheets"

    if is_note_intent(text):
        return "note"

    if is_memory_intent(text):
        return "memory"

    if is_debug_intent(text):
        print("SUPERVISOR: natural language debug intent")
        return "debug"

    if is_weather_intent(text):
        print("SUPERVISOR: weather intent")
        return "weather"

    print("SUPERVISOR: unsupported")
    return "unsupported"


def supervisor_node(state: AgentState) -> AgentState:
    raw_message = state.get("raw_message", "")

    intent = classify_intent(raw_message)
    next_agent = _INTENT_TO_AGENT.get(intent, "fallback")

    user_id = state.get("user_id")
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

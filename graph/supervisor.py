"""
LangGraph Phase1: Supervisorノード。

責務:
- raw_message からintentを判定する
- next_agent を決定する

やらないこと:
- Agentの実行
- LINE返信生成

Phase1では debug のみ Debug Agentへ振り分ける。
"""

from app_development import extract_app_development_request
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
    "app_development": "app_development",
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

    # 明示的なアプリ開発依頼はCore Agentとして最優先で扱う。
    # 実行時の認可はapp_development.py側で行う。
    if extract_app_development_request(text) is not None:
        print("SUPERVISOR: app development intent")
        return "app_development"

    # Sheets明示・自然文を先に判定する。
    # 「シートに記録 明日の予定」のように、Notesの汎用キーワード
    # （予定・したい・名前等）を含む場合でもSheetsを優先する。
    if is_sheets_intent(text):
        print("SUPERVISOR: sheets intent")
        return "sheets"

    # 「メモに、明日の10時にテストすると保存して」のように、
    # メモ依頼の本文に日時が含まれていてもNotesへルーティングする。
    # 「はい」のような保留中の確認も、元のuser_idを渡してNotes側で処理する。
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
    """
    Supervisorノード本体。

    Supervisorでintent判定とnext_agent決定のみ行う。
    """
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

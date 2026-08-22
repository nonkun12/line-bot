"""
LangGraph Phase1: Supervisorノード。

責務:
- raw_message から intent を判定する
- next_agent を決定する

やらないこと:
- Agentの実行
- LINE返信生成

Phase1では debug のみ Debug Agentへ振り分ける。
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
    # "unsupported" (=GitHub/Debug/Memory/Notesのいずれにも該当しない通常
    # メッセージ) は、旧 generate_reply() 末尾にあった通常のGroq応答へ
    # 振り分ける。以前はここが "fallback" 固定になっており、
    # 通常のAI応答ルートが存在していなかった(未移植の原因)。
    "unsupported": "normal",
}


def classify_intent(raw_message: str) -> str:
    """
    メッセージ内容からintentを判定する。
    Phase1ではdebugプレフィックスとNotes系コマンドを対応させる。
    """
    text = (raw_message or "").strip()

    print("===== SUPERVISOR =====")
    print("RAW:", text)

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

    # 「debug」プレフィックスなしの自然文(例: 「app.pyのエラーを確認して」)
    # からのDebug Agentルーティング。既存Agent(GitHub/Sheets/Notes/Memory)
    # の判定より後に置くことで、既存の誤ルーティング防止を優先する。
    if is_debug_intent(text):
        print("SUPERVISOR: natural language debug intent")
        return "debug"

    print("SUPERVISOR: unsupported")
    return "unsupported"


def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisorノード本体。

    intent判定とnext_agent決定のみ行う。
    """
    raw_message = state.get("raw_message", "")

    intent = classify_intent(raw_message)
    next_agent = _INTENT_TO_AGENT.get(
        intent,
        "fallback"
    )

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

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


_DEBUG_PREFIX = "debug"


_INTENT_TO_AGENT = {
    "debug": "debug",
    "unsupported": "fallback",
}


def classify_intent(raw_message: str) -> str:
    """
    メッセージ内容からintentを判定する。
    Phase1ではdebugプレフィックスのみ対応。
    """
    text = (raw_message or "").strip()

    if text.startswith(_DEBUG_PREFIX):
        return "debug"

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

    return {
        **state,
        "intent": intent,
        "next_agent": next_agent,
    }

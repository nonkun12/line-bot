"""
LangGraph Phase1: Debug Agent Adapter

注意:
このファイルはLangGraph用のアダプターです。

実際の解析処理:
    debug_agent.run_debug_agent()

を呼び出すだけです。

既存:
    debug_agent/

のread_only設計は変更しません。
"""


from debug_agent import run_debug_agent
from graph.state import AgentState


def _strip_debug_prefix(message: str) -> str:
    """
    debug xxx の xxx 部分だけ取り出す
    """

    text = message or ""

    if text.startswith("debug"):
        return text.replace("debug", "", 1).strip()

    return text.strip()


def debug_agent_node(state: AgentState) -> AgentState:
    """
    LangGraph Debug Agentノード
    """

    message = state.get("raw_message", "")

    error_text = _strip_debug_prefix(message)

    try:
        result = run_debug_agent(error_text)

    except Exception as e:
        result = (
            "🔍 AI Debug Agent\n\n"
            f"解析エラー:\n{e}"
        )

    agent_results = dict(
        state.get("agent_results", {})
    )

    agent_results["debug"] = result

    return {
        **state,
        "agent_results": agent_results,
    }
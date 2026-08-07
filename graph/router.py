"""
LangGraph Phase1: Router

責務:
- Supervisorが決定した next_agent を確認
- 実際のLangGraphノード名へ変換する

Supervisor:
    「何をするか決める」

Router:
    「どのノードへ移動するか決める」

この分離によりPhase2以降でAgent追加が容易になる。
"""

from graph.state import AgentState


_ROUTE_TABLE = {
    "debug": "debug_agent",
    "notes": "notes_agent",
    "memory": "memory_agent",
"github": "github_agent",
    "fallback": "fallback_agent",
}

_DEFAULT_ROUTE = "fallback_agent"


def route_from_supervisor(state: AgentState) -> str:
    """
    LangGraphのadd_conditional_edgesで使用する分岐関数。

    未知のnext_agentの場合は安全側として
    fallback_agentへ送る。
    """

    next_agent = state.get("next_agent")

    print("===== ROUTER =====")
    print("next_agent =", next_agent)
    print("route =", _ROUTE_TABLE.get(next_agent, _DEFAULT_ROUTE))

    return _ROUTE_TABLE.get(
        next_agent,
        _DEFAULT_ROUTE
    )
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

from core.agents import AgentRegistry
from core.langgraph_router import route_with_core
from graph.core_registry import LEGACY_GRAPH_NODES


_ROUTE_TABLE = LEGACY_GRAPH_NODES
_DEFAULT_ROUTE = LEGACY_GRAPH_NODES["fallback"]


def route_from_supervisor(
    state: AgentState,
    registry: AgentRegistry | None = None,
) -> str:
    """
    LangGraphのadd_conditional_edgesで使用する分岐関数。

    registryが渡された場合はCore Registryを先に評価し、未解決なら
    既存の固定ルートへフォールバックする。省略時の挙動は従来と同一。
    """

    if registry is not None:
        route = route_with_core(
            state,
            registry,
            legacy_routes=_ROUTE_TABLE,
            default_route=_DEFAULT_ROUTE,
        )
        # The legacy graph has only a fixed set of named nodes. Future/Core-only
        # agents may resolve successfully in the shared registry, but must not
        # be returned as nonexistent legacy graph nodes.
        if route not in _ROUTE_TABLE.values():
            route = _DEFAULT_ROUTE
    else:
        next_agent = state.get("next_agent")
        route = _ROUTE_TABLE.get(next_agent, _DEFAULT_ROUTE)

    print("===== ROUTER =====")
    print("next_agent =", state.get("next_agent"))
    print("route =", route)

    return route

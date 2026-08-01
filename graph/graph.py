"""
LangGraph Phase1 graph definition

構成:

START
 ↓
Supervisor
 ↓
Conditional Router
 ↓
Debug Agent / Fallback
 ↓
(Debug Agentルートのみ) Fix Agent → Patch Agent → Test Agent
 ↓
Finalizer
 ↓
END

既存 app.py には接続しない。

Phase4a:
- patch_agent / test_agent を追加。
- AUTO_APPLY_PATCH=false (デフォルト) の場合、
  patch_agentは何もせず素通りするだけなので、
  Fix Agentまでの既存動作は変わらない。
- commit_agentを追加。deploy_agentはまだ追加しない(Phase4cで対応)。
"""

from langgraph.graph import StateGraph, START, END

from graph.state import AgentState
from graph.supervisor import supervisor_node
from graph.router import route_from_supervisor
from agents.debug.node import debug_agent_node
from agents.fix.node import fix_agent_node
from agents.patch.node import patch_apply_node
from agents.test.node import test_runner_node
from agents.commit.node import commit_node
from agents.deploy.node import deploy_node


def fallback_node(state: AgentState) -> AgentState:
    """
    未対応Agent用の仮ノード
    """

    results = dict(
        state.get("agent_results", {})
    )

    results["fallback"] = (
        "この機能はLangGraph Phase1では未対応です。"
    )

    return {
        **state,
        "agent_results": results,
    }


def finalize_node(state: AgentState) -> AgentState:
    """
    最終返信生成ノード
    Phase1では単純に結果を返すだけ
    """

    results = state.get("agent_results", {})

    if state.get("next_agent") == "debug":
        debug_result = results.get(
            "debug",
            {}
        )

        reply = debug_result.get(
            "text",
            "解析結果なし"
        )
    else:
        reply = results.get(
            "fallback",
            "対応できません"
        )

    return {
        **state,
        "final_reply": reply,
    }


def build_graph():

    builder = StateGraph(AgentState)

    builder.add_node(
        "supervisor",
        supervisor_node
    )

    builder.add_node(
        "debug_agent",
        debug_agent_node
    )

    builder.add_node(
        "fix_agent",
        fix_agent_node
    )

    builder.add_node(
        "patch_agent",
        patch_apply_node
    )

    builder.add_node(
        "test_agent",
        test_runner_node
    )

    builder.add_node(
        "commit_agent",
        commit_node
    )

    builder.add_node(
        "deploy_agent",
        deploy_node
    )

    builder.add_node(
        "fallback_agent",
        fallback_node
    )

    builder.add_node(
        "finalizer",
        finalize_node
    )


    builder.add_edge(
        START,
        "supervisor"
    )


    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "debug_agent": "debug_agent",
            "fallback_agent": "fallback_agent",
        },
    )


    builder.add_edge(
        "debug_agent",
        "fix_agent"
    )

    builder.add_edge(
        "fix_agent",
        "patch_agent"
    )

    builder.add_edge(
        "patch_agent",
        "test_agent"
    )

    builder.add_edge(
        "test_agent",
        "commit_agent"
    )

    builder.add_edge(
        "commit_agent",
        "deploy_agent"
    )

    builder.add_edge(
        "deploy_agent",
        "finalizer"
    )

    builder.add_edge(
        "fallback_agent",
        "finalizer"
    )

    builder.add_edge(
        "finalizer",
        END
    )


    return builder.compile()


graph = build_graph()

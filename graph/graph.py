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
(Debug Agentルートのみ)
Fix Agent → Patch Generate Agent → Patch Agent → Test Agent
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

Phase3 (Patch Agent基盤):
- fix_agentとpatch_agent(Phase4a適用ノード)の間に
  patch_generate_agentを追加。
- Fix Agentの結果からPatch候補(PatchCandidate)を生成するのみで、
  実際のファイル変更・git操作は一切行わない。
- 既存のpatch_agent(適用ロジック)は無変更。
"""

from langgraph.graph import StateGraph, START, END

from graph.state import AgentState
from graph.supervisor import supervisor_node
from graph.router import route_from_supervisor
from agents.debug.node import debug_agent_node
from dev_notes.wrappers.graph_node_wrapper import with_execution_logging
from dev_notes.factory import get_default_adapter


debug_agent_node = with_execution_logging(
    debug_agent_node,
    "debug",
    get_default_adapter(),
)
from agents.fix.node import fix_agent_node
from agents.patch.node import patch_apply_node, patch_generate_node
from agents.test.node import test_runner_node
from agents.commit.node import commit_node
from agents.deploy.node import deploy_node

# Wrap LangGraph agent nodes with dev_notes execution logging.
# Wrappers are added only — original logic inside each node is unchanged.
fix_agent_node = with_execution_logging(
    fix_agent_node,
    "fix",
    get_default_adapter(),
)

patch_generate_node = with_execution_logging(
    patch_generate_node,
    "patch_generate",
    get_default_adapter(),
)

patch_apply_node = with_execution_logging(
    patch_apply_node,
    "patch_apply",
    get_default_adapter(),
)

test_runner_node = with_execution_logging(
    test_runner_node,
    "test",
    get_default_adapter(),
)

commit_node = with_execution_logging(
    commit_node,
    "commit",
    get_default_adapter(),
)

deploy_node = with_execution_logging(
    deploy_node,
    "deploy",
    get_default_adapter(),
)


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

    Debug / Fix / Patch / Test / Commit / Deploy
    各Agent結果をまとめて返す。
    """

    results = state.get("agent_results", {})

    if not results:
        reply = "対応できません"

    elif "fallback" in results:
        reply = results.get(
            "fallback",
            "対応できません"
        )

    else:
        lines = []

        debug_result = results.get(
            "debug",
            {}
        )

        if debug_result:
            lines.append(
                "【Debug】\n"
                + debug_result.get(
                    "text",
                    ""
                )
            )

        fix_result = results.get(
            "fix",
            {}
        )

        if fix_result:
            lines.append(
                "【Fix】\n"
                + fix_result.get(
                    "summary",
                    ""
                )
            )

        patch_result = results.get(
            "patch",
            {}
        )

        if patch_result:
            lines.append(
                "【Patch】\n"
                + str(patch_result)
            )

        test_result = results.get(
            "test",
            {}
        )

        if test_result:
            lines.append(
                "【Test】\n"
                + str(test_result)
            )

        commit_result = results.get(
            "commit",
            {}
        )

        if commit_result:
            lines.append(
                "【Commit】\n"
                + str(commit_result)
            )

        deploy_result = results.get(
            "deploy",
            {}
        )

        if deploy_result:
            lines.append(
                "【Deploy】\n"
                + str(deploy_result)
            )

        reply = "\n\n".join(lines)

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
        "patch_generate_agent",
        patch_generate_node
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
        "patch_generate_agent"
    )

    builder.add_edge(
        "patch_generate_agent",
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

"""
LangGraph Phase1 graph definition.

Worker mode is opt-in: the existing module-level ``graph`` keeps its current
behavior, while ``build_worker_graph()`` enables persistent checkpoints and
node-boundary interrupts for one-step-at-a-time execution.
"""

import os
import sqlite3

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from graph.state import AgentState
from graph.supervisor import supervisor_node
from graph.router import route_from_supervisor
from agents.debug.node import debug_agent_node
from agents.memory.node import memory_agent_node
from agents.notes.node import notes_agent_node
from agents.github.node import github_agent_node
from agents.sheets.node import sheets_agent_node
from agents.normal.node import normal_agent_node
from agents.weather.node import weather_agent_node
from agents.work_status.node import work_status_agent_node
from dev_notes.wrappers.graph_node_wrapper import with_execution_logging
from dev_notes.factory import get_default_adapter


debug_agent_node = with_execution_logging(debug_agent_node, "debug", get_default_adapter())
notes_agent_node = with_execution_logging(notes_agent_node, "notes", get_default_adapter())
memory_agent_node = with_execution_logging(memory_agent_node, "memory", get_default_adapter())
normal_agent_node = with_execution_logging(normal_agent_node, "normal", get_default_adapter())
work_status_agent_node = with_execution_logging(work_status_agent_node, "work_status", get_default_adapter())

from agents.fix.node import fix_agent_node
from agents.patch.node import patch_apply_node, patch_generate_node
from agents.test.node import test_runner_node
from agents.commit.node import commit_node
from agents.deploy.node import deploy_node

fix_agent_node = with_execution_logging(fix_agent_node, "fix", get_default_adapter())
patch_generate_node = with_execution_logging(patch_generate_node, "patch_generate", get_default_adapter())
patch_apply_node = with_execution_logging(patch_apply_node, "patch_apply", get_default_adapter())
test_runner_node = with_execution_logging(test_runner_node, "test", get_default_adapter())
commit_node = with_execution_logging(commit_node, "commit", get_default_adapter())
deploy_node = with_execution_logging(deploy_node, "deploy", get_default_adapter())


def fallback_node(state: AgentState) -> AgentState:
    results = dict(state.get("agent_results", {}))
    results["fallback"] = "この機能はLangGraph Phase1では未対応です。"
    return {**state, "agent_results": results}


def finalize_node(state: AgentState) -> AgentState:
    results = state.get("agent_results", {})
    print("===== FINALIZER =====")
    print("agent_results =", results)

    if not results:
        reply = "対応できません"
    elif "fallback" in results:
        reply = results.get("fallback", "対応できません")
    else:
        lines = []
        for key, label, field in (
            ("debug", "Debug", "text"),
            ("notes", "Notes", "text"),
            ("memory", "Memory", "text"),
            ("weather", "Weather", "text"),
            ("work_status", None, "text"),
            ("normal", None, "text"),
            ("github", "GitHub", "text"),
            ("sheets", "Sheets", "text"),
            ("fix", "Fix", "summary"),
        ):
            value = results.get(key, {})
            if not value:
                continue
            text = value.get(field, "") if isinstance(value, dict) else str(value)
            lines.append(f"【{label}】\n{text}" if label else text)
        for key, label in (("patch", "Patch"), ("test", "Test"), ("commit", "Commit"), ("deploy", "Deploy")):
            value = results.get(key, {})
            if value:
                lines.append(f"【{label}】\n{value}")
        reply = "\n\n".join(line for line in lines if line)

    return {**state, "final_reply": reply}


def route_from_debug(state: AgentState) -> str:
    try:
        has_traceback = state["agent_results"]["debug"]["structured"]["error_info"]["has_traceback"]
    except (KeyError, TypeError):
        return "finalizer"
    return "fix_agent" if has_traceback is True else "finalizer"


WORKER_STEP_NODES = [
    "supervisor",
    "debug_agent",
    "notes_agent",
    "memory_agent",
    "normal_agent",
    "work_status_agent",
    "fix_agent",
    "patch_generate_agent",
    "patch_agent",
    "test_agent",
    "github_agent",
    "sheets_agent",
    "weather_agent",
    "fallback_agent",
]

WORKER_APPROVAL_NODES = ["commit_agent", "deploy_agent"]


def _build_checkpointer():
    path = os.environ.get(
        "LANGGRAPH_CHECKPOINT_DB",
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "langgraph-checkpoints.sqlite3",
        ),
    )
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)


def build_graph(*, checkpointer=None, interrupt_after=None, interrupt_before=None):
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("debug_agent", debug_agent_node)
    builder.add_node("notes_agent", notes_agent_node)
    builder.add_node("memory_agent", memory_agent_node)
    builder.add_node("normal_agent", normal_agent_node)
    builder.add_node("work_status_agent", work_status_agent_node)
    builder.add_node("fix_agent", fix_agent_node)
    builder.add_node("patch_generate_agent", patch_generate_node)
    builder.add_node("patch_agent", patch_apply_node)
    builder.add_node("test_agent", test_runner_node)
    builder.add_node("commit_agent", commit_node)
    builder.add_node("github_agent", github_agent_node)
    builder.add_node("sheets_agent", sheets_agent_node)
    builder.add_node("weather_agent", weather_agent_node)
    builder.add_node("deploy_agent", deploy_node)
    builder.add_node("fallback_agent", fallback_node)
    builder.add_node("finalizer", finalize_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "debug_agent": "debug_agent",
            "notes_agent": "notes_agent",
            "memory_agent": "memory_agent",
            "github_agent": "github_agent",
            "sheets_agent": "sheets_agent",
            "normal_agent": "normal_agent",
            "weather_agent": "weather_agent",
            "work_status_agent": "work_status_agent",
            "fallback_agent": "fallback_agent",
        },
    )
    builder.add_conditional_edges(
        "debug_agent",
        route_from_debug,
        {"fix_agent": "fix_agent", "finalizer": "finalizer"},
    )
    for node in (
        "notes_agent", "memory_agent", "normal_agent", "github_agent",
        "sheets_agent", "weather_agent", "work_status_agent", "fallback_agent",
    ):
        builder.add_edge(node, "finalizer")
    builder.add_edge("fix_agent", "patch_generate_agent")
    builder.add_edge("patch_generate_agent", "patch_agent")
    builder.add_edge("patch_agent", "test_agent")
    builder.add_edge("test_agent", "commit_agent")
    builder.add_edge("commit_agent", "deploy_agent")
    builder.add_edge("deploy_agent", "finalizer")
    builder.add_edge("finalizer", END)

    kwargs = {}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if interrupt_after is not None:
        kwargs["interrupt_after"] = interrupt_after
    if interrupt_before is not None:
        kwargs["interrupt_before"] = interrupt_before
    return builder.compile(**kwargs)


def build_worker_graph():
    """Return the persisted, interrupt-driven graph used by the Job Worker."""
    return build_graph(
        checkpointer=_build_checkpointer(),
        interrupt_after=WORKER_STEP_NODES,
        interrupt_before=WORKER_APPROVAL_NODES,
    )


graph = build_graph()

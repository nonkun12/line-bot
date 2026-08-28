"""
LangGraph Phase1 graph definition.

Worker integration:
- persist graph state with a SQLite checkpointer;
- stop after each processing node so one Worker call advances one node;
- stop before commit/deploy so the Worker can enforce approval.
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
        debug_result = results.get("debug", {})
        if debug_result:
            lines.append("【Debug】\n" + debug_result.get("text", ""))
        notes_result = results.get("notes", {})
        if notes_result:
            lines.append("【Notes】\n" + notes_result.get("text", ""))
        memory_result = results.get("memory", {})
        if memory_result:
            lines.append("【Memory】\n" + memory_result.get("text", ""))
        weather_result = results.get("weather", {})
        if weather_result:
            lines.append("【Weather】\n" + weather_result.get("text", ""))
        work_status_result = results.get("work_status", {})
        if work_status_result:
            lines.append(work_status_result.get("text", ""))
        normal_result = results.get("normal", {})
        if normal_result:
            lines.append(normal_result.get("text", ""))
        github_result = results.get("github", {})
        if github_result:
            lines.append("【GitHub】\n" + github_result.get("text", ""))
        sheets_result = results.get("sheets", {})
        if sheets_result:
            lines.append("【Sheets】\n" + sheets_result.get("text", ""))
        fix_result = results.get("fix", {})
        if fix_result:
            lines.append("【Fix】\n" + fix_result.get("summary", ""))
        for key, label in (("patch", "Patch"), ("test", "Test"), ("commit", "Commit"), ("deploy", "Deploy")):
            value = results.get(key, {})
            if value:
                lines.append(f"【{label}】\n" + str(value))
        reply = "\n\n".join(line for line in lines if line)

    return {**state, "final_reply": reply}


def route_from_debug(state: AgentState) -> str:
    try:
        has_traceback = state["agent_results"]["debug"]["structured"]["error_info"]["has_traceback"]
    except (KeyError, TypeError):
        return "finalizer"
    return "fix_agent" if has_traceback is True else "finalizer"


# One Worker execution advances one logical graph node.
# Commit/deploy are intentionally excluded from the after-breakpoint list because
# they are protected by a before-breakpoint and must never run without Worker approval.
STEP_NODES_AFTER = [
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
    "finalizer",
]

APPROVAL_NODES_BEFORE = ["commit_agent", "deploy_agent"]


def _build_checkpointer():
    path = os.environ.get(
        "LANGGRAPH_CHECKPOINT_DB",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "langgraph-checkpoints.sqlite3"),
    )
    conn = sqlite3.connect(path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def build_graph():
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
        "notes_agent",
        "memory_agent",
        "normal_agent",
        "github_agent",
        "sheets_agent",
        "weather_agent",
        "work_status_agent",
        "fallback_agent",
    ):
        builder.add_edge(node, "finalizer")

    builder.add_edge("fix_agent", "patch_generate_agent")
    builder.add_edge("patch_generate_agent", "patch_agent")
    builder.add_edge("patch_agent", "test_agent")
    builder.add_edge("test_agent", "commit_agent")
    builder.add_edge("commit_agent", "deploy_agent")
    builder.add_edge("deploy_agent", "finalizer")
    builder.add_edge("finalizer", END)

    return builder.compile(
        checkpointer=_build_checkpointer(),
        interrupt_after=STEP_NODES_AFTER,
        interrupt_before=APPROVAL_NODES_BEFORE,
    )


graph = build_graph()

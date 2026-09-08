import importlib.util
import os
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver


for key in (
    "CHANNEL_ACCESS_TOKEN",
    "CHANNEL_SECRET",
    "GROQ_API_KEY",
    "MCP_SERVER_URL",
    "MCP_API_KEY",
    "INTERNAL_PUSH_KEY",
):
    os.environ.setdefault(key, "test-value")

STANDALONE_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = STANDALONE_DIR.parent

# Preload the repository-root db module so standalone-agent/db.py does not
# shadow it for other tests during a single pytest process.
_ROOT_DB_SPEC = importlib.util.spec_from_file_location("db", ROOT_DIR / "db.py")
_ROOT_DB = importlib.util.module_from_spec(_ROOT_DB_SPEC)
sys.modules["db"] = _ROOT_DB
assert _ROOT_DB_SPEC.loader is not None
_ROOT_DB_SPEC.loader.exec_module(_ROOT_DB)

sys.path.insert(0, str(STANDALONE_DIR))

import graph.graph as graph_module


def test_worker_graph_resumes_one_node_per_invoke(monkeypatch):
    def fake_supervisor(state):
        return {**state, "intent": "fallback"}

    monkeypatch.setattr(graph_module, "supervisor_node", fake_supervisor)
    monkeypatch.setattr(
        graph_module,
        "route_from_supervisor",
        lambda state: "fallback_agent",
    )

    worker_graph = graph_module.build_graph(
        checkpointer=InMemorySaver(),
        interrupt_after=["supervisor", "fallback_agent", "finalizer"],
    )

    config = {"configurable": {"thread_id": "job-123"}}
    initial_state = {
        "user_id": "test-user",
        "raw_message": "test",
        "agent_results": {},
    }

    worker_graph.invoke(initial_state, config)
    assert worker_graph.get_state(config).next == ("fallback_agent",)

    worker_graph.invoke(None, config)
    assert worker_graph.get_state(config).next == ("finalizer",)

    worker_graph.invoke(None, config)
    assert worker_graph.get_state(config).next == ()


def test_development_job_starts_at_development_agent():
    assert graph_module.route_from_start({"job_type": "development"}) == "development_agent"
    assert graph_module.route_from_start({"job_type": "ai_task"}) == "supervisor"


def test_development_path_reaches_test_agent():
    worker_graph = graph_module.build_graph(checkpointer=InMemorySaver())
    graph = worker_graph.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("development_agent", "test_agent") in edges


def test_failed_test_routes_back_to_debug():
    assert graph_module.route_from_test({"test_result": {"passed": False}}) == "debug_agent"
    assert graph_module.route_from_test({"test_result": {"passed": True}}) == "commit_agent"


def test_debug_routes_failed_test_to_fix():
    state = {"test_result": {"passed": False}, "agent_results": {}}
    assert graph_module.route_from_debug(state) == "fix_agent"


def test_debug_routes_traceback_to_fix():
    state = {
        "test_result": {},
        "agent_results": {
            "debug": {"structured": {"error_info": {"has_traceback": True}}}
        },
    }
    assert graph_module.route_from_debug(state) == "fix_agent"


def test_debug_without_actionable_error_finishes():
    state = {
        "test_result": {},
        "agent_results": {
            "debug": {"structured": {"error_info": {"has_traceback": False}}}
        },
    }
    assert graph_module.route_from_debug(state) == "finalizer"


def test_merge_and_deploy_routes_require_success():
    assert graph_module.route_from_commit({"commit_result": {"committed": True}}) == "publish_agent"
    assert graph_module.route_from_publish({"publish_result": {"published": True}}) == "merge_agent"
    assert graph_module.route_from_merge({"merge_result": {"merged": True}}) == "deploy_agent"
    assert graph_module.route_from_merge({"merge_result": {"merged": False}}) == "finalizer"


def test_development_graph_has_bounded_repair_and_release_path():
    worker_graph = graph_module.build_graph(checkpointer=InMemorySaver())
    graph = worker_graph.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    expected_edges = {
        ("development_agent", "test_agent"),
        ("test_agent", "debug_agent"),
        ("debug_agent", "fix_agent"),
        ("fix_agent", "patch_generate_agent"),
        ("patch_generate_agent", "patch_agent"),
        ("patch_agent", "test_agent"),
        ("test_agent", "commit_agent"),
        ("commit_agent", "publish_agent"),
        ("publish_agent", "merge_agent"),
        ("merge_agent", "deploy_agent"),
        ("deploy_agent", "finalizer"),
    }
    assert expected_edges <= edges

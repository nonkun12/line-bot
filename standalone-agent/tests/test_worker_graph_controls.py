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

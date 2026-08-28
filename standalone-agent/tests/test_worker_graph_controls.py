import os
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver


# graph imports transitively load standalone-agent/config.py.
# This test never calls LINE/Groq/MCP, so use harmless dummy values.
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
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(STANDALONE_DIR))

import graph.graph as graph_module


def test_worker_graph_resumes_one_node_per_invoke(monkeypatch):
    """A worker-mode graph must advance one node per invocation on one thread."""

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
        interrupt_after=("supervisor", "fallback_agent", "finalizer"),
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

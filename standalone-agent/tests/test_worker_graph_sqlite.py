import os
import sqlite3
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


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


def test_worker_graph_persists_and_resumes_with_sqlite(tmp_path, monkeypatch):
    def fake_supervisor(state):
        return {**state, "intent": "fallback"}

    monkeypatch.setattr(graph_module, "supervisor_node", fake_supervisor)
    monkeypatch.setattr(
        graph_module,
        "route_from_supervisor",
        lambda state: "fallback_agent",
    )

    db_path = tmp_path / "checkpoint.sqlite"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    worker_graph = graph_module.build_graph(
        checkpointer=saver,
        interrupt_after=["supervisor", "fallback_agent"],
    )

    config = {"configurable": {"thread_id": "job-sqlite-1"}}
    initial_state = {
        "user_id": "test-user",
        "raw_message": "test",
        "request_id": "job-sqlite-1",
        "agent_results": {},
    }

    worker_graph.invoke(initial_state, config)
    first = worker_graph.get_state(config)
    assert first.next == ("fallback_agent",)
    assert first.values["intent"] == "fallback"

    # Re-create the graph around the same SQLite database to prove persistence.
    conn.close()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver2 = SqliteSaver(conn)
    saver2.setup()
    worker_graph2 = graph_module.build_graph(
        checkpointer=saver2,
        interrupt_after=["supervisor", "fallback_agent"],
    )

    resumed = worker_graph2.get_state(config)
    assert resumed.next == ("fallback_agent",)
    assert resumed.values["intent"] == "fallback"

    worker_graph2.invoke(None, config)
    # fallback_agent was the second breakpoint; finalizer is the next node.
    assert worker_graph2.get_state(config).next == ("finalizer",)
    worker_graph2.invoke(None, config)
    assert worker_graph2.get_state(config).next == ()
    conn.close()

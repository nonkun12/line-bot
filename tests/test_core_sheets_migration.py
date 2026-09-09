from core.langgraph_runtime import agent_node_name
from graph.core_graph import build_current_core_graph
import agents.sheets.node as sheets_node


def test_current_core_graph_executes_sheets_agent_through_registry(monkeypatch):
    class FakeClient:
        pass

    monkeypatch.setattr(sheets_node, "GoogleSheetsClient", lambda spreadsheet_id=None: FakeClient())
    monkeypatch.setattr(
        sheets_node,
        "handle_sheets_message",
        lambda message, user_id, client: {
            "text": "Google Sheetsに記録しました：テスト",
            "success": True,
        },
    )

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "シートにテストを記録して",
            "next_agent": "sheets",
            "agent_results": {},
        }
    )

    assert result["route"] == agent_node_name("sheets")
    assert result["final_reply"] == "Google Sheetsに記録しました：テスト"
    assert result["agent_results"]["sheets"]["text"] == "Google Sheetsに記録しました：テスト"

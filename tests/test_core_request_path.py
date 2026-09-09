from core.gateway import AIRequest, AIGateway
from core.request_path import extract_core_reply, run_core_request
from core.langgraph_runtime import agent_node_name
import agents.notes.node as notes_node


def test_run_core_request_classifies_and_executes_notes(monkeypatch):
    monkeypatch.setattr(
        notes_node,
        "handle_note_message",
        lambda message, user_id, call_mcp_tool: "メモ「テスト」を保存しました。",
    )

    result = run_core_request("u1", "メモにテストを保存して")

    assert result["intent"] == "note"
    assert result["next_agent"] == "notes"
    assert result["route"] == agent_node_name("notes")
    assert result["final_reply"] == "メモ「テスト」を保存しました。"
    assert result["agent_results"]["notes"]["text"] == "メモ「テスト」を保存しました。"


def test_extract_core_reply_uses_final_reply():
    assert extract_core_reply({"final_reply": "OK"}) == "OK"
    assert extract_core_reply({}) == "Agent結果なし"


def test_gateway_contract_accepts_core_response():
    gateway = AIGateway(lambda request: "OK")
    response = gateway.handle(
        AIRequest(user_id="u1", message="テスト", channel="line")
    )
    assert response.text == "OK"

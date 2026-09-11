from graph.supervisor import classify_intent, supervisor_node
from core import AgentRegistry, build_core_graph
from agents.normal.node import agent as normal_agent


def test_unsupported_intent_maps_to_normal_agent_and_core_fallback_is_not_used() -> None:
    message = "これは既存機能に該当しないランダムな相談です"
    assert classify_intent(message, user_id="test-user") == "unsupported"

    supervised = supervisor_node(
        {
            "user_id": "test-user",
            "raw_message": message,
            "channel": "line",
            "metadata": {},
        }
    )
    assert supervised["intent"] == "unsupported"
    assert supervised["next_agent"] == "normal"


def test_dynamic_core_graph_routes_unknown_request_to_normal_when_registered() -> None:
    message = "これは既存機能に該当しないランダムな相談です"
    supervised = supervisor_node(
        {
            "user_id": "test-user",
            "raw_message": message,
            "channel": "line",
            "metadata": {},
        }
    )

    registry = AgentRegistry([normal_agent])
    graph = build_core_graph(registry, fallback_text="CORE FALLBACK")
    result = graph.invoke(supervised)

    assert result["route"] != "core_fallback"
    assert "normal" in result["agent_results"]
    assert result["final_reply"]

from core.agents import AgentRegistry, AgentRequest, AgentResponse
import graph.graph as graph_module


class RegistryRouteAgent:
    name = "weather"
    description = "test registry route"
    priority = 100
    enabled = True
    graph_node = "normal_agent"

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("next_agent") == "weather"

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="unused")


def test_build_graph_uses_core_registry_before_legacy_route(monkeypatch):
    registry = AgentRegistry([RegistryRouteAgent()])

    monkeypatch.setattr(graph_module, "build_core_agent_registry", lambda: registry)
    monkeypatch.setattr(
        graph_module,
        "supervisor_node",
        lambda state: {**state, "next_agent": "weather"},
    )
    monkeypatch.setattr(
        graph_module,
        "normal_agent_node",
        lambda state: {
            **state,
            "agent_results": {
                **state.get("agent_results", {}),
                "normal": {"text": "core route won"},
            },
        },
    )
    monkeypatch.setattr(
        graph_module,
        "finalize_node",
        lambda state: {**state, "final_reply": "core route won"},
    )

    compiled = graph_module.build_graph()
    result = compiled.invoke(
        {
            "user_id": "u1",
            "raw_message": "天気",
            "agent_results": {},
        }
    )

    assert result["final_reply"] == "core route won"
    assert result["agent_results"]["normal"]["text"] == "core route won"

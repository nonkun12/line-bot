from core.agents import AgentRegistry, AgentRequest, AgentResponse
from core.langgraph_runtime import agent_node_name, build_core_graph


class CalendarAgent:
    name = "calendar"
    description = "calendar"
    priority = 10
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("intent") == "calendar"

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="予定OK", metadata={"source": "calendar"})


class StringAgent:
    name = "string-agent"
    description = "string response agent"
    priority = 5
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("intent") == "string"

    def handle(self, request: AgentRequest) -> str:
        return "文字列OK"


class HighPriorityAgent:
    name = "high"
    description = "high priority"
    priority = 20
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("intent") == "shared"

    def handle(self, request: AgentRequest) -> str:
        return "high"


class LowPriorityAgent:
    name = "low"
    description = "low priority"
    priority = 1
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("intent") == "shared"

    def handle(self, request: AgentRequest) -> str:
        return "low"


class UnicodeNameAgent:
    name = "旅行計画"
    description = "unicode agent"
    priority = 1
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return request.metadata.get("intent") == "travel"

    def handle(self, request: AgentRequest) -> str:
        return "旅行OK"


def test_agent_node_name_is_stable_and_unique_for_unicode():
    assert agent_node_name("calendar") == agent_node_name("calendar")
    assert agent_node_name("calendar") != agent_node_name("旅行計画")


def test_registered_agent_is_executed_as_dynamic_graph_node():
    graph = build_core_graph(AgentRegistry([CalendarAgent()]))

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "予定を確認",
            "next_agent": "calendar",
            "intent": "calendar",
        }
    )

    assert result["final_reply"] == "予定OK"
    assert result["agent_results"]["calendar"]["metadata"]["source"] == "calendar"


def test_string_agent_response_is_normalized():
    graph = build_core_graph(AgentRegistry([StringAgent()]))

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "test",
            "intent": "string",
        }
    )

    assert result["final_reply"] == "文字列OK"


def test_generic_resolution_uses_registry_priority():
    graph = build_core_graph(AgentRegistry([LowPriorityAgent(), HighPriorityAgent()]))

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "shared",
            "intent": "shared",
        }
    )

    assert result["final_reply"] == "high"
    assert result["agent_results"]["high"]["text"] == "high"


def test_arbitrary_unicode_agent_name_is_executable():
    agent = UnicodeNameAgent()
    graph = build_core_graph(AgentRegistry([agent]))

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "旅行計画",
            "next_agent": agent.name,
            "intent": "travel",
        }
    )

    assert result["final_reply"] == "旅行OK"
    assert result["agent_results"][agent.name]["text"] == "旅行OK"


def test_unknown_agent_falls_back():
    graph = build_core_graph(AgentRegistry())

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "unknown",
            "next_agent": "missing",
        }
    )

    assert result["final_reply"] == "対応できるAgentが登録されていません。"


def test_disabled_explicit_agent_does_not_execute():
    agent = CalendarAgent()
    agent.enabled = False
    graph = build_core_graph(AgentRegistry([agent]))

    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "予定を確認",
            "next_agent": "calendar",
            "intent": "calendar",
        }
    )

    assert result["final_reply"] == "対応できるAgentが登録されていません。"
    assert "calendar" not in result.get("agent_results", {})

from core.langgraph_runtime import agent_node_name
from graph.core_graph import build_current_core_graph
import agents.weather.node as weather_node


def test_current_core_graph_executes_weather_agent_through_registry(monkeypatch):
    monkeypatch.setattr(
        weather_node,
        "_get_weather",
        lambda latitude, longitude: {
            "current": {
                "temperature_2m": 27.4,
                "temperature_2m_unit": "°C",
                "weather_code": 1,
            }
        },
    )

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "東京の天気を教えて",
            "next_agent": "weather",
            "agent_results": {},
        }
    )

    assert result["route"] == agent_node_name("weather")
    assert "東京の現在の天気です。" in result["final_reply"]
    assert "晴れ" in result["final_reply"]
    assert "27.4°C" in result["final_reply"]
    assert result["agent_results"]["weather"]["metadata"]["success"] is True
    assert result["agent_results"]["weather"]["metadata"]["provider"] == "open-meteo"


def test_current_core_graph_weather_failure_returns_safe_agent_response(monkeypatch):
    def fail_weather(latitude, longitude):
        raise RuntimeError("private upstream detail")

    monkeypatch.setattr(weather_node, "_get_weather", fail_weather)

    graph = build_current_core_graph()
    result = graph.invoke(
        {
            "user_id": "u1",
            "raw_message": "東京の天気を教えて",
            "next_agent": "weather",
            "agent_results": {},
        }
    )

    assert result["final_reply"] == "天気情報を取得できませんでした。"
    assert result["agent_results"]["weather"]["metadata"]["success"] is False
    assert result["agent_results"]["weather"]["metadata"]["provider"] == "open-meteo"

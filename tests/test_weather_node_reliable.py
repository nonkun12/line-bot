from agents.weather.node import _geocode_location, _extract_weather_location, weather_agent_node


def test_requested_locations_are_extracted():
    assert _extract_weather_location("東京の天気は？") == "東京"
    assert _extract_weather_location("京都の天気") == "京都"
    assert _extract_weather_location("沖縄の天気は？") == "沖縄"
    assert _extract_weather_location("天気 京都") == "京都"


def test_known_locations_do_not_require_geocoding():
    assert _geocode_location("京都") == ("京都", 35.0116, 135.7681)
    assert _geocode_location("沖縄") == ("沖縄", 26.2124, 127.6809)


def test_weather_node_uses_requested_coordinates(monkeypatch):
    captured = {}

    def fake_get_weather(latitude, longitude):
        captured["coords"] = (latitude, longitude)
        return {
            "current": {
                "temperature_2m": 24.5,
                "temperature_2m_unit": "°C",
                "weather_code": 1,
            }
        }

    monkeypatch.setattr("agents.weather.node._get_weather", fake_get_weather)
    result = weather_agent_node({"raw_message": "京都の天気は？", "agent_results": {}})

    assert captured["coords"] == (35.0116, 135.7681)
    assert result["agent_results"]["weather"]["success"] is True
    assert result["agent_results"]["weather"]["location"] == "京都"
    assert "京都の現在の天気です。" in result["agent_results"]["weather"]["text"]

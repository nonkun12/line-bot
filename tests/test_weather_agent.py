from unittest.mock import patch

from agents.weather.node import _extract_weather_location, _geocode_location, weather_agent_node


def test_extract_shizuoka_weather_location():
    assert _extract_weather_location("静岡の天気は？") == "静岡"


def test_shizuoka_uses_deterministic_coordinates_without_geocoder():
    with patch("agents.weather.node.requests.get") as get:
        assert _geocode_location("静岡") == ("静岡", 34.9756, 138.3828)
        get.assert_not_called()


def test_weather_agent_returns_success_for_shizuoka_with_weather_api():
    payload = {
        "current": {
            "temperature_2m": 25.1,
            "temperature_2m_unit": "°C",
            "weather_code": 1,
        }
    }
    with patch("agents.weather.node.requests.get") as get:
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = payload

        result = weather_agent_node({"raw_message": "静岡の天気は？", "agent_results": {}})

    assert result["agent_results"]["weather"]["success"] is True
    assert result["agent_results"]["weather"]["location"] == "静岡"
    assert "気温: 25.1°C" in result["agent_results"]["weather"]["text"]
    get.assert_called_once()

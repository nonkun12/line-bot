from unittest.mock import patch

from agents.weather.node import (
    _extract_weather_location,
    _geocode_location,
    weather_agent_node,
)


def test_extract_weather_locations_from_common_japanese_phrasing():
    assert _extract_weather_location("静岡の天気は？") == "静岡"
    assert _extract_weather_location("札幌市の現在の天気") == "札幌市"
    assert _extract_weather_location("天気は福岡") == "福岡"


def test_prefecture_names_use_deterministic_nationwide_fallbacks():
    assert _geocode_location("静岡県") == ("静岡県", 34.9756, 138.3828)
    assert _geocode_location("青森県") == ("青森県", 40.8244, 140.7400)
    assert _geocode_location("沖縄県") == ("沖縄県", 26.2124, 127.6809)


def test_prefecture_fallback_does_not_call_geocoder():
    with patch("agents.weather.node.requests.get") as get:
        _geocode_location("大阪府")
        get.assert_not_called()


def test_city_resolution_uses_japan_filtered_geocoder():
    response = {
        "results": [
            {
                "name": "浜松",
                "latitude": 34.7108,
                "longitude": 137.7261,
                "country_code": "JP",
                "admin1": "静岡県",
                "feature_code": "PPL",
                "population": 788000,
            },
            {
                "name": "浜松",
                "latitude": 40.0,
                "longitude": 140.0,
                "country_code": "XX",
                "feature_code": "PPL",
                "population": 9999999,
            },
        ]
    }
    with patch("agents.weather.node.requests.get") as get:
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = response

        result = _geocode_location("浜松市")

    assert result == ("浜松", 34.7108, 137.7261)
    params = get.call_args.kwargs["params"]
    assert params["countryCode"] == "JP"
    assert params["count"] == 10


def test_city_resolution_retries_after_empty_result():
    first = {"results": []}
    second = {
        "results": [{
            "name": "静岡市",
            "latitude": 34.9756,
            "longitude": 138.3828,
            "country_code": "JP",
            "admin1": "静岡県",
            "feature_code": "PPL",
            "population": 693000,
        }]
    }
    with patch("agents.weather.node.requests.get") as get:
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.side_effect = [first, second]

        result = _geocode_location("静岡市")

    assert result == ("静岡市", 34.9756, 138.3828)
    assert get.call_count == 2


def test_weather_agent_returns_success_for_shizuoka():
    geocode_payload = {
        "results": [{
            "name": "静岡市",
            "latitude": 34.9756,
            "longitude": 138.3828,
            "country_code": "JP",
            "admin1": "静岡県",
            "feature_code": "PPL",
            "population": 693000,
        }]
    }
    weather_payload = {
        "current": {
            "temperature_2m": 25.1,
            "temperature_2m_unit": "°C",
            "weather_code": 1,
        }
    }
    with patch("agents.weather.node.requests.get") as get:
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.side_effect = [geocode_payload, weather_payload]

        result = weather_agent_node({"raw_message": "静岡市の天気は？", "agent_results": {}})

    assert result["agent_results"]["weather"]["success"] is True
    assert result["agent_results"]["weather"]["location"] == "静岡市"
    assert "気温: 25.1°C" in result["agent_results"]["weather"]["text"]
    assert get.call_count == 2

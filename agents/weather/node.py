"""
Weather Agent LangGraph node.

Uses Open-Meteo without an API key.
"""

from __future__ import annotations

import requests


def _weather_code_text(code: int) -> str:
    codes = {
        0: "快晴",
        1: "晴れ",
        2: "晴れ時々曇り",
        3: "曇り",
        45: "霧",
        48: "霧",
        51: "弱い霧雨",
        53: "霧雨",
        55: "強い霧雨",
        61: "弱い雨",
        63: "雨",
        65: "強い雨",
        71: "弱い雪",
        73: "雪",
        75: "強い雪",
        80: "にわか雨",
        81: "にわか雨",
        82: "強いにわか雨",
        95: "雷雨",
        96: "雷雨",
        99: "強い雷雨",
    }
    return codes.get(code, f"天気コード {code}")


def _get_weather(latitude: float, longitude: float) -> dict:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "Asia/Tokyo",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def weather_agent_node(state):
    """Fetch current Tokyo weather and return it to the finalizer."""

    try:
        data = _get_weather(35.6762, 139.6503)
        current = data.get("current", {})

        temperature = current.get("temperature_2m")
        unit = current.get("temperature_2m_unit", "°C")
        code = current.get("weather_code")

        if temperature is None or code is None:
            raise RuntimeError("Open-Meteo returned incomplete weather data")

        text = (
            "東京の現在の天気です。\n"
            f"天気: {_weather_code_text(int(code))}\n"
            f"気温: {temperature}{unit}"
        )

        result = {
            "text": text,
            "success": True,
            "provider": "open-meteo",
        }

    except Exception as exc:
        print("[WEATHER ERROR]", exc)
        result = {
            "text": "天気情報を取得できませんでした。",
            "success": False,
            "provider": "open-meteo",
            "error": str(exc),
        }

    results = dict(state.get("agent_results", {}))
    results["weather"] = result

    return {
        **state,
        "agent_results": results,
    }

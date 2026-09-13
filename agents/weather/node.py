"""
Weather Agent LangGraph node.

Uses Open-Meteo without an API key.
"""

from __future__ import annotations

import re

import requests


_WEATHER_LOCATION_RE = re.compile(
    r"(?P<location>[\w々ー一-龯ぁ-んァ-ヶ]+?)(?:の)?"
    r"(?:現在の)?(?:天気|天候|気温|温度|降水確率|雨|雪|晴れ|曇り|weather|temperature|forecast)",
    re.IGNORECASE,
)

_WEATHER_PREFIX_RE = re.compile(
    r"(?:天気|天候|気温|温度|weather|temperature|forecast)\s*(?:は|の)?\s*"
    r"(?P<location>[\w々ー一-龯ぁ-んァ-ヶ]+)",
    re.IGNORECASE,
)

# Avoid making the availability of a third-party geocoder a hard dependency
# for the common Japanese locations users ask about.
_KNOWN_LOCATIONS: dict[str, tuple[str, float, float]] = {
    "東京": ("東京", 35.6762, 139.6503),
    "東京都": ("東京都", 35.6762, 139.6503),
    "京都": ("京都", 35.0116, 135.7681),
    "京都市": ("京都市", 35.0116, 135.7681),
    "沖縄": ("沖縄", 26.2124, 127.6809),
    "那覇": ("那覇", 26.2124, 127.6809),
    "那覇市": ("那覇市", 26.2124, 127.6809),
}


def _weather_code_text(code: int) -> str:
    codes = {
        0: "快晴", 1: "晴れ", 2: "晴れ時々曇り", 3: "曇り",
        45: "霧", 48: "霧", 51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨",
        61: "弱い雨", 63: "雨", 65: "強い雨", 71: "弱い雪", 73: "雪",
        75: "強い雪", 80: "にわか雨", 81: "にわか雨", 82: "強いにわか雨",
        95: "雷雨", 96: "雷雨", 99: "強い雷雨",
    }
    return codes.get(code, f"天気コード {code}")


def _extract_weather_location(message: str) -> str | None:
    """Extract a location from common Japanese/English weather questions."""
    text = (message or "").strip()
    if not text:
        return None

    match = _WEATHER_LOCATION_RE.search(text)
    if match:
        return match.group("location").strip("？?。！!、 ") or None

    match = _WEATHER_PREFIX_RE.search(text)
    if match:
        return match.group("location").strip("？?。！!、 ") or None

    return None


def _geocode_location(location: str) -> tuple[str, float, float]:
    """Resolve a place name to coordinates, preferring deterministic local mappings."""
    known = _KNOWN_LOCATIONS.get(location)
    if known is not None:
        return known

    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": location,
            "count": 1,
            "language": "ja",
            "format": "json",
        },
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise ValueError(f"場所が見つかりません: {location}")
    result = results[0]
    return (
        str(result.get("name") or location),
        float(result["latitude"]),
        float(result["longitude"]),
    )


def _get_weather(latitude: float, longitude: float) -> dict:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "Asia/Tokyo",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def weather_agent_node(state):
    """Fetch current weather for the location named in the user's message."""
    try:
        message = str(state.get("raw_message", ""))
        location = _extract_weather_location(message)
        if not location:
            raise ValueError("天気を調べる地域を特定できませんでした")

        resolved_name, latitude, longitude = _geocode_location(location)
        data = _get_weather(latitude, longitude)
        current = data.get("current", {})
        temperature = current.get("temperature_2m")
        unit = current.get("temperature_2m_unit", "°C")
        code = current.get("weather_code")

        if temperature is None or code is None:
            raise RuntimeError("Open-Meteo returned incomplete weather data")

        result = {
            "text": (
                f"{resolved_name}の現在の天気です。\n"
                f"天気: {_weather_code_text(int(code))}\n"
                f"気温: {temperature}{unit}"
            ),
            "success": True,
            "provider": "open-meteo",
            "location": resolved_name,
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
    return {**state, "agent_results": results}

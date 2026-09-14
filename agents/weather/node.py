"""
Weather Agent LangGraph node.

Uses Open-Meteo without an API key.
"""

from __future__ import annotations

import re
import time

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

# Deterministic fallback for prefecture-level requests. City/town requests are
# resolved through the Japan-filtered geocoder below.
_PREFECTURE_FALLBACKS: dict[str, tuple[str, float, float]] = {
    "北海道": ("北海道", 43.0646, 141.3468),
    "青森県": ("青森県", 40.8244, 140.7400),
    "岩手県": ("岩手県", 39.7036, 141.1527),
    "宮城県": ("宮城県", 38.2682, 140.8694),
    "秋田県": ("秋田県", 39.7186, 140.1024),
    "山形県": ("山形県", 38.2404, 140.3633),
    "福島県": ("福島県", 37.7503, 140.4676),
    "茨城県": ("茨城県", 36.3418, 140.4468),
    "栃木県": ("栃木県", 36.5658, 139.8836),
    "群馬県": ("群馬県", 36.3911, 139.0608),
    "埼玉県": ("埼玉県", 35.8569, 139.6489),
    "千葉県": ("千葉県", 35.6051, 140.1233),
    "東京都": ("東京都", 35.6762, 139.6503),
    "神奈川県": ("神奈川県", 35.4478, 139.6425),
    "新潟県": ("新潟県", 37.9026, 139.0236),
    "富山県": ("富山県", 36.6953, 137.2113),
    "石川県": ("石川県", 36.5947, 136.6256),
    "福井県": ("福井県", 36.0652, 136.2216),
    "山梨県": ("山梨県", 35.6639, 138.5683),
    "長野県": ("長野県", 36.6513, 138.1810),
    "岐阜県": ("岐阜県", 35.3912, 136.7223),
    "静岡県": ("静岡県", 34.9756, 138.3828),
    "愛知県": ("愛知県", 35.1802, 136.9066),
    "三重県": ("三重県", 34.7303, 136.5086),
    "滋賀県": ("滋賀県", 35.0045, 135.8686),
    "京都府": ("京都府", 35.0210, 135.7556),
    "大阪府": ("大阪府", 34.6863, 135.5197),
    "兵庫県": ("兵庫県", 34.6913, 135.1830),
    "奈良県": ("奈良県", 34.6851, 135.8049),
    "和歌山県": ("和歌山県", 34.2260, 135.1675),
    "鳥取県": ("鳥取県", 35.5039, 134.2383),
    "島根県": ("島根県", 35.4723, 133.0505),
    "岡山県": ("岡山県", 34.6618, 133.9344),
    "広島県": ("広島県", 34.3963, 132.4596),
    "山口県": ("山口県", 34.1861, 131.4705),
    "徳島県": ("徳島県", 34.0658, 134.5593),
    "香川県": ("香川県", 34.3401, 134.0434),
    "愛媛県": ("愛媛県", 33.8416, 132.7657),
    "高知県": ("高知県", 33.5597, 133.5311),
    "福岡県": ("福岡県", 33.6064, 130.4183),
    "佐賀県": ("佐賀県", 33.2494, 130.2988),
    "長崎県": ("長崎県", 32.7448, 129.8737),
    "熊本県": ("熊本県", 32.7898, 130.7417),
    "大分県": ("大分県", 33.2382, 131.6126),
    "宮崎県": ("宮崎県", 31.9111, 131.4239),
    "鹿児島県": ("鹿児島県", 31.5602, 130.5581),
    "沖縄県": ("沖縄県", 26.2124, 127.6809),
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


def _normalize_location(location: str) -> str:
    value = re.sub(r"[\s　]+", "", (location or "")).strip("？?。！!、,，")
    if value.endswith("の"):
        value = value[:-1]
    return value


def _geocoding_candidates(location: str) -> list[dict]:
    """Resolve a Japanese place using JP-filtered Open-Meteo results and retries."""
    queries = [location]
    if location.endswith(("県", "府", "都", "道")):
        queries.append(location[:-1])
    elif not location.endswith(("市", "区", "町", "村")):
        queries.append(f"{location}市")
    queries.append(f"{location}, Japan")

    last_error: Exception | None = None
    for query in dict.fromkeys(queries):
        for attempt in range(2):
            try:
                response = requests.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={
                        "name": query,
                        "count": 10,
                        "language": "ja",
                        "format": "json",
                        "countryCode": "JP",
                    },
                    timeout=10,
                )
                response.raise_for_status()
                results = response.json().get("results") or []
                if results:
                    return results
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.15)

    if last_error:
        raise last_error
    return []


def _geocode_location(location: str) -> tuple[str, float, float]:
    """Resolve a Japanese place nationwide, preferring exact JP matches."""
    normalized = _normalize_location(location)
    known = _PREFECTURE_FALLBACKS.get(normalized)
    if known is not None:
        return known

    candidates = _geocoding_candidates(normalized)
    if not candidates:
        raise ValueError(f"場所が見つかりません: {location}")

    target = normalized
    target_base = re.sub(r"(?:都|道|府|県|市|区|町|村)$", "", target)

    jp_candidates = [
        result
        for result in candidates
        if str(result.get("country_code") or "").upper() == "JP"
    ]
    if not jp_candidates:
        raise ValueError(f"日本国内の場所が見つかりません: {location}")

    def score(result: dict) -> tuple[int, int, int]:
        name = _normalize_location(str(result.get("name") or ""))
        admin1 = _normalize_location(str(result.get("admin1") or ""))
        feature = str(result.get("feature_code") or "")
        exact = int(name == target)
        base_match = int(bool(target_base) and (name == target_base or name.startswith(target_base)))
        admin_match = int(bool(admin1) and (admin1 == target or admin1.startswith(target_base)))
        place_bonus = int(feature.startswith("PPL"))
        population = int(result.get("population") or 0)
        return (exact * 8 + admin_match * 3 + base_match + place_bonus, exact + admin_match, population // 100000)

    result = max(jp_candidates, key=score)
    return (
        str(result.get("name") or location),
        float(result["latitude"]),
        float(result["longitude"]),
    )


def _get_weather(latitude: float, longitude: float) -> dict:
    """Fetch current weather, retrying transient provider failures."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
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
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.15)
    assert last_error is not None
    raise last_error


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

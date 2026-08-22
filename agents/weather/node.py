"""
Weather Agent LangGraph node.

Uses Open-Meteo without an API key.
"""

from __future__ import annotations

import time

import requests


# =========================
# 主要都市の静的な緯度経度テーブル
# =========================
# 以前はどんな地名でも毎回 Open-Meteo の geocoding API に問い合わせていたが、
# 「京都」のような短い地名で geocoding が結果を返さなかった場合、
# 何のログも残さず無条件に東京の座標へフォールバックしてしまい、
# 「京都と聞かれたのに東京の天気を返す」という誤動作が発生していた。
# 主要都市はこのテーブルで即座に解決することで、
# (1) 誤った地名解決を防ぎ、(2) geocoding API への問い合わせ回数を減らし
#     レート制限(429)の発生も抑える。
KNOWN_CITY_COORDS = {
    "東京": (35.6762, 139.6503),
    "京都": (35.0116, 135.7681),
    "大阪": (34.6937, 135.5023),
    "横浜": (35.4437, 139.6380),
    "名古屋": (35.1815, 136.9066),
    "札幌": (43.0618, 141.3545),
    "福岡": (33.5904, 130.4017),
    "神戸": (34.6901, 135.1955),
    "仙台": (38.2682, 140.8694),
    "広島": (34.3853, 132.4553),
    "那覇": (26.2124, 127.6809),
    "さいたま": (35.8617, 139.6455),
    "千葉": (35.6074, 140.1065),
    "新潟": (37.9161, 139.0364),
    "金沢": (36.5613, 136.6562),
    "長野": (36.6513, 138.1811),
}

# 地名の末尾に付きがちな行政区分の接尾辞を取り除いてテーブル照合しやすくする
_CITY_SUFFIXES = ("都", "府", "県", "市")

# 地名 -> (取得時刻, 結果文字列) の簡易キャッシュ。
# 同一地名への短時間の再問い合わせを減らし、429の再発リスクを下げる。
_WEATHER_CACHE_TTL_SECONDS = 300
_weather_cache: dict[str, tuple[float, str]] = {}


def _normalize_city_name(name: str) -> str:
    stripped = name.strip()
    for suffix in _CITY_SUFFIXES:
        if len(stripped) > len(suffix) and stripped.endswith(suffix):
            return stripped[: -len(suffix)]
    return stripped


def _lookup_known_city(name: str) -> tuple[float, float, str] | None:
    candidates = (name, _normalize_city_name(name))
    for candidate in candidates:
        if candidate in KNOWN_CITY_COORDS:
            lat, lon = KNOWN_CITY_COORDS[candidate]
            return lat, lon, candidate
    return None


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


def get_weather_report(location: str | None = None) -> str:
    """Fetch current weather for a named location."""
    target = (location or "東京").strip() or "東京"

    cached = _weather_cache.get(target)
    if cached and (time.time() - cached[0]) < _WEATHER_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        known = _lookup_known_city(target)

        if known:
            latitude, longitude, display_name = known
        else:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": target,
                    "count": 1,
                    "language": "ja",
                    "format": "json",
                },
                timeout=10,
            )
            geo.raise_for_status()
            results = geo.json().get("results") or []

            if results:
                place = results[0]
                latitude = float(place["latitude"])
                longitude = float(place["longitude"])
                display_name = place.get("name", target)
            else:
                # 地名が解決できなかった場合、以前は無条件に東京へフォールバック
                # していたが、それではユーザーが聞いていない地名の天気を
                # 誤って返してしまう(例: 「京都」→ 実際は東京の天気)。
                # 解決できないことをログに残し、正直にエラーを返す。
                print(f"[WEATHER ERROR] location not resolved: {target!r}")
                return f"「{target}」の場所を特定できず、天気情報を取得できませんでした。"

        data = _get_weather(latitude, longitude)
        current = data.get("current", {})
        temperature = current.get("temperature_2m")
        unit = current.get("temperature_2m_unit", "°C")
        code = current.get("weather_code")

        if temperature is None or code is None:
            raise RuntimeError("Open-Meteo returned incomplete weather data")

        report = (
            f"{display_name}の現在の天気です。\n"
            f"天気: {_weather_code_text(int(code))}\n"
            f"気温: {temperature}{unit}"
        )
        _weather_cache[target] = (time.time(), report)
        return report

    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 429:
            print(f"[WEATHER ERROR] rate_limited location={target!r}: {exc}")
            return "天気情報の取得回数が上限に達しています。しばらくしてからもう一度お試しください。"
        print(f"[WEATHER ERROR] http_error location={target!r}: {exc}")
        return f"{target}の天気情報を取得できませんでした。"

    except Exception as exc:
        print(f"[WEATHER ERROR] location={target!r}: {exc}")
        return f"{target}の天気情報を取得できませんでした。"

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

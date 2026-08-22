import requests

from agents.weather import node as weather_node


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Too Many Requests for url: ..."
            )
            error.response = self
            raise error

    def json(self):
        return self._json_data


def _forecast_response(temperature=20.0, code=1):
    return _FakeResponse(
        200,
        {
            "current": {
                "temperature_2m": temperature,
                "temperature_2m_unit": "°C",
                "weather_code": code,
            }
        },
    )


def setup_function(_):
    # 各テスト間でキャッシュを共有しないようにクリアする
    weather_node._weather_cache.clear()


def test_kyoto_uses_known_kyoto_coordinates_not_tokyo(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        assert "geocoding-api.open-meteo.com" not in url, (
            "既知の都市(京都)は geocoding API を呼ばずに解決すべき"
        )
        captured["latitude"] = params["latitude"]
        captured["longitude"] = params["longitude"]
        return _forecast_response()

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    result = weather_node.get_weather_report("京都")

    assert "京都" in result
    # 東京の座標(35.6762, 139.6503)になっていないことを確認
    assert captured["latitude"] == weather_node.KNOWN_CITY_COORDS["京都"][0]
    assert captured["longitude"] == weather_node.KNOWN_CITY_COORDS["京都"][1]


def test_tokyo_still_works(monkeypatch):
    monkeypatch.setattr(
        weather_node.requests, "get", lambda url, params=None, timeout=None: _forecast_response()
    )

    result = weather_node.get_weather_report("東京")
    assert "東京" in result


def test_osaka_still_works(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["latitude"] = params["latitude"]
        captured["longitude"] = params["longitude"]
        return _forecast_response()

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    result = weather_node.get_weather_report("大阪")

    assert "大阪" in result
    assert captured["latitude"] == weather_node.KNOWN_CITY_COORDS["大阪"][0]
    assert captured["longitude"] == weather_node.KNOWN_CITY_COORDS["大阪"][1]


def test_unknown_location_uses_geocoding_and_reports_honestly_when_unresolved(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "geocoding-api.open-meteo.com" in url:
            return _FakeResponse(200, {"results": []})
        raise AssertionError("地名が解決できない場合、forecast APIを呼んではいけない")

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    result = weather_node.get_weather_report("存在しない架空の地名XYZ")

    # 東京の天気にすり替わっていないこと、正直にエラーを返すこと
    assert "東京" not in result
    assert "特定できず" in result


def test_unknown_location_resolved_via_geocoding(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "geocoding-api.open-meteo.com" in url:
            return _FakeResponse(
                200,
                {"results": [{"name": "ニューヨーク", "latitude": 40.7128, "longitude": -74.0060}]},
            )
        return _forecast_response()

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    result = weather_node.get_weather_report("ニューヨーク")
    assert "ニューヨーク" in result


def test_open_meteo_429_gives_clear_message_not_generic_failure(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(429, {})

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    result = weather_node.get_weather_report("京都")

    assert "上限" in result or "しばらく" in result


def test_repeated_call_uses_cache_and_avoids_second_request(monkeypatch):
    call_count = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        call_count["n"] += 1
        return _forecast_response()

    monkeypatch.setattr(weather_node.requests, "get", fake_get)

    first = weather_node.get_weather_report("京都")
    second = weather_node.get_weather_report("京都")

    assert first == second
    assert call_count["n"] == 1

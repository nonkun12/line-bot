from agents.weather.node import _extract_weather_location


def test_extract_weather_location_from_japanese_questions():
    assert _extract_weather_location("東京の天気は？") == "東京"
    assert _extract_weather_location("京都の天気") == "京都"
    assert _extract_weather_location("沖縄の天気は？") == "沖縄"


def test_extract_weather_location_from_weather_prefix():
    assert _extract_weather_location("天気 京都") == "京都"

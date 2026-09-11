from app_development import extract_app_development_request


def test_explicit_japanese_prefix_is_required():
    assert extract_app_development_request("アプリ開発: 家計簿アプリを作って") == "家計簿アプリを作って"
    assert extract_app_development_request("アプリを作って") is None


def test_empty_explicit_request_is_preserved():
    assert extract_app_development_request("アプリ開発:") == ""


def test_english_prefix_is_supported():
    assert extract_app_development_request("app-dev: build a tiny todo web app") == "build a tiny todo web app"

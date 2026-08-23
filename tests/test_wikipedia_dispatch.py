import bot_tools



def test_dispatch_routes_wikipedia_through_normal_package_wrapper(monkeypatch):
    import agents.normal as normal_package

    monkeypatch.setattr(
        normal_package,
        "wikipedia_search",
        lambda query: f"summary for {query}",
    )

    result = bot_tools.dispatch_tool_call(
        "u1",
        "wikipedia_search",
        {"query": "東京タワー"},
    )

    assert result == "summary for 東京タワー"


def test_dispatch_wikipedia_exception_is_handled(monkeypatch):
    import agents.normal as normal_package

    def raise_error(query):
        raise RuntimeError("network error")

    monkeypatch.setattr(normal_package, "wikipedia_search", raise_error)

    result = bot_tools.dispatch_tool_call(
        "u1",
        "wikipedia_search",
        {"query": "東京タワー"},
    )

    assert result == "Wikipedia検索中にエラーが発生しました。"


def test_dispatch_existing_tool_falls_through_to_original(monkeypatch):
    import agents.normal as normal_package

    calls = {}

    def fake_original(user_id, name, arguments, original_message=""):
        calls["args"] = (user_id, name, arguments, original_message)
        return "original result"

    monkeypatch.setattr(normal_package, "_original_dispatch_tool_call", fake_original)

    result = bot_tools.dispatch_tool_call(
        "u1",
        "save_note",
        {"title": "t", "body": "b"},
        original_message="test",
    )

    assert result == "original result"
    assert calls["args"] == (
        "u1",
        "save_note",
        {"title": "t", "body": "b"},
        "test",
    )

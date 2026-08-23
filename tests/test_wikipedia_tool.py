from unittest.mock import Mock, patch

import requests

from wikipedia_tool import WIKIPEDIA_TOOL_SCHEMA, wikipedia_search


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_wikipedia_tool_schema_has_query_parameter():
    function = WIKIPEDIA_TOOL_SCHEMA["function"]
    assert function["name"] == "wikipedia_search"
    assert "query" in function["parameters"]["properties"]
    assert function["parameters"]["required"] == ["query"]


def test_wikipedia_search_returns_summary_and_url():
    search_payload = {
        "query": {
            "search": [
                {"title": "東京タワー", "snippet": "東京の電波塔"}
            ]
        }
    }
    summary_payload = {
        "extract": "東京タワーは東京都港区にある総合電波塔です。",
        "content_urls": {
            "desktop": {"page": "https://ja.wikipedia.org/wiki/%E6%9D%B1%E4%BA%AC%E3%82%BF%E3%83%AF%E3%83%BC"}
        },
    }

    with patch(
        "wikipedia_tool.requests.get",
        side_effect=[_response(search_payload), _response(summary_payload)],
    ) as get:
        result = wikipedia_search("東京タワー")

    assert "【Wikipedia】東京タワー" in result
    assert "東京タワーは東京都港区" in result
    assert "https://ja.wikipedia.org/wiki/" in result
    assert get.call_count == 2


def test_wikipedia_search_handles_empty_query_without_request():
    with patch("wikipedia_tool.requests.get") as get:
        result = wikipedia_search("   ")

    assert result == "Wikipedia検索語が空です。"
    get.assert_not_called()


def test_wikipedia_search_reports_no_results():
    with patch(
        "wikipedia_tool.requests.get",
        return_value=_response({"query": {"search": []}}),
    ):
        result = wikipedia_search("存在しない検索語")

    assert "一致する記事が見つかりませんでした" in result


def test_wikipedia_search_uses_snippet_when_summary_fails():
    search_payload = {
        "query": {
            "search": [
                {"title": "東京タワー", "snippet": "東京の電波塔"}
            ]
        }
    }
    failure = requests.RequestException("summary unavailable")

    with patch(
        "wikipedia_tool.requests.get",
        side_effect=[_response(search_payload), failure],
    ):
        result = wikipedia_search("東京タワー")

    assert "【Wikipedia】東京タワー" in result
    assert "東京の電波塔" in result
    assert "URL:" not in result

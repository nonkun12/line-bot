"""Wikipedia search tool for the Normal Agent.

Uses the official Japanese Wikipedia APIs directly and returns a concise,
LLM-friendly result for function calling.
"""

from __future__ import annotations

from urllib.parse import quote

import requests


WIKIPEDIA_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "wikipedia_search",
        "description": (
            "日本語Wikipediaを検索して、ユーザーが指定した話題の概要を取得する。"
            "ユーザーが『Wikipediaで調べて』『Wikipediaについて教えて』など、"
            "Wikipedia検索を明示的に求めた場合に必ず使用する。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Wikipediaで検索する話題。例: 東京タワー"
                }
            },
            "required": ["query"]
        }
    }
}


def wikipedia_search(query: str) -> str:
    """Search Japanese Wikipedia and return the top article summary."""
    query = (query or "").strip()
    if not query:
        return "Wikipedia検索語が空です。"

    headers = {
        "User-Agent": "LINE-AI-Secretary/1.0 (Wikipedia tool)"
    }

    search_response = requests.get(
        "https://ja.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "formatversion": 2,
            "utf8": 1,
            "srlimit": 3,
        },
        headers=headers,
        timeout=10,
    )
    search_response.raise_for_status()
    search_data = search_response.json()
    results = (search_data.get("query") or {}).get("search") or []

    if not results:
        return f"Wikipediaで「{query}」に一致する記事が見つかりませんでした。"

    top = results[0]
    title = top.get("title") or query

    try:
        summary_response = requests.get(
            f"https://ja.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}",
            headers=headers,
            timeout=10,
        )
        summary_response.raise_for_status()
        summary = summary_response.json()
        extract = (summary.get("extract") or "").strip()
        page_url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
    except requests.RequestException as exc:
        print("[WIKIPEDIA ERROR] summary lookup failed:", exc)
        extract = ""
        page_url = None

    if extract:
        result_text = f"【Wikipedia】{title}\n{extract}"
    else:
        snippet = (top.get("snippet") or "").strip()
        result_text = f"【Wikipedia】{title}\n{snippet or '概要を取得できませんでした。'}"

    if page_url:
        result_text += f"\nURL: {page_url}"

    return result_text

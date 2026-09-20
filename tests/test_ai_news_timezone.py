from __future__ import annotations

from agents.news.node import AINewsAgent


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_news_pubdate_is_rendered_in_japan_time(monkeypatch) -> None:
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel>
      <item>
        <title>Test AI News</title>
        <link>https://example.com/news</link>
        <pubDate>Fri, 11 Sep 2026 20:00:00 +0000</pubDate>
        <source>Test Source</source>
      </item>
    </channel></rss>"""

    monkeypatch.setattr(
        "agents.news.node.urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(payload),
    )

    items = AINewsAgent._fetch("artificial intelligence")

    assert len(items) == 1
    assert items[0]["published"] == "09/12 05:00"


def test_news_duplicate_links_are_removed_and_limit_is_applied(monkeypatch) -> None:
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel>
      <item><title>One</title><link>https://example.com/a</link></item>
      <item><title>One duplicate</title><link>https://example.com/a</link></item>
      <item><title>Two</title><link>https://example.com/b</link></item>
      <item><title>Three</title><link>https://example.com/c</link></item>
    </channel></rss>"""

    monkeypatch.setattr(
        "agents.news.node.urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(payload),
    )

    items = AINewsAgent._fetch("artificial intelligence")

    assert [item["link"] for item in items] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]

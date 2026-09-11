"""AI news agent with a dependency-free RSS retrieval MVP."""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from core.agents import AgentRequest, AgentResponse


_JST = ZoneInfo("Asia/Tokyo")


class AINewsAgent:
    name = "ai_news"
    description = "AI news retrieval, summarization, and delivery requests."
    priority = 80
    enabled = True

    _KEYWORDS = ("AI NEWS", "AIニュース", "AI ニュース", "人工知能ニュース", "ai news")
    _RSS_BASE = "https://news.google.com/rss/search"
    _TIMEOUT_SEC = 8
    _MAX_ITEMS = 5

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(keyword.lower() in text for keyword in self._KEYWORDS)

    @classmethod
    def _query(cls, message: str) -> str:
        normalized = re.sub(r"\s+", " ", message.strip())
        for keyword in cls._KEYWORDS:
            normalized = re.sub(re.escape(keyword), "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(教えて|見せて|ください|お願い|最新|ニュース|を|が)+$", "", normalized).strip()
        return normalized or "artificial intelligence"

    @classmethod
    def _feed_url(cls, query: str) -> str:
        params = {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
        return cls._RSS_BASE + "?" + urllib.parse.urlencode(params)

    @staticmethod
    def _clean_text(value: str) -> str:
        value = html.unescape(value or "")
        return re.sub(r"<[^>]+>", "", value).strip()

    @classmethod
    def _fetch(cls, query: str) -> list[dict[str, str]]:
        request = urllib.request.Request(
            cls._feed_url(query),
            headers={"User-Agent": "LINE-AI-Secretary/1.0"},
        )
        with urllib.request.urlopen(request, timeout=cls._TIMEOUT_SEC) as response:
            root = ET.fromstring(response.read())

        items: list[dict[str, str]] = []
        for item in root.findall("./channel/item")[: cls._MAX_ITEMS]:
            title = cls._clean_text(item.findtext("title", ""))
            link = item.findtext("link", "")
            published = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            if not title or not link:
                continue
            try:
                parsed = (
                    parsedate_to_datetime(published)
                    .astimezone(_JST)
                    .strftime("%m/%d %H:%M")
                    if published
                    else ""
                )
            except (TypeError, ValueError, OverflowError):
                parsed = published
            items.append({"title": title, "link": link, "published": parsed, "source": source})
        return items

    def handle(self, request: AgentRequest) -> AgentResponse:
        query = self._query(request.message)
        try:
            items = self._fetch(query)
        except Exception:
            return AgentResponse(
                text="AI NEWSを取得できませんでした。外部ニュース源が一時的に利用できない可能性があります。",
                metadata={"feature": self.name, "status": "degraded", "query": query, "count": 0},
            )

        if not items:
            return AgentResponse(
                text=f"AI NEWSの検索結果が見つかりませんでした。検索語: {query}",
                metadata={"feature": self.name, "status": "online", "query": query, "count": 0},
            )

        lines = [f"📰 AI NEWS（{query}）"]
        for index, item in enumerate(items, 1):
            suffix = f" / {item['source']}" if item["source"] else ""
            date = f" / {item['published']}" if item["published"] else ""
            lines.append(f"{index}. {item['title']}{suffix}{date}\n{item['link']}")

        return AgentResponse(
            text="\n".join(lines),
            metadata={"feature": self.name, "status": "online", "query": query, "count": len(items)},
        )


agent = AINewsAgent()


def ai_news_agent_node(state: dict) -> dict:
    request = AgentRequest(
        user_id=str(state.get("user_id", "")),
        message=str(state.get("raw_message", "")),
        channel=str(state.get("channel", "unknown")),
        metadata=state.get("metadata", {}),
    )
    response = agent.handle(request)
    return {"final_reply": response.text, "agent_results": {agent.name: response.text}}

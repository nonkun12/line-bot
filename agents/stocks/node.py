"""Stock-query agent with a safe no-provider fallback."""
from __future__ import annotations

import re

from core.agents import AgentRequest, AgentResponse
from agents.stocks.intents import is_stock_intent


_TICKER_RE = re.compile(r"(?:銘柄|ticker|コード)\s*[:：]?\s*([A-Za-z]{1,6}[.]?[A-Za-z]{0,3}|\d{4})")


class StocksAgent:
    name = "stocks"
    description = "Stock price, ticker, watchlist, and market requests."
    priority = 80
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_stock_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        match = _TICKER_RE.search(request.message)
        ticker = match.group(1).upper() if match else None
        if ticker:
            text = (
                f"📈 株価リクエストを受け付けました: {ticker}\n\n"
                "現在この環境には市場データプロバイダが未接続のため、"
                "価格を推測して表示することはしません。\n"
                "次の段階でリアルタイム市場データ取得を接続します。"
            )
        else:
            text = (
                "📈 株価Agentを起動しました。\n\n"
                "銘柄コードまたはTickerを含めて送ってください。"
                "例: 「銘柄 7203」「ticker AAPL」\n"
                "市場データ接続前なので、架空の株価は表示しません。"
            )
        return AgentResponse(
            text=text,
            metadata={"feature": self.name, "status": "planned", "ticker": ticker},
        )


agent = StocksAgent()

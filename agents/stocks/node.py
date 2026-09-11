"""Safe stock-query agent scaffold; live market provider is added separately."""
from __future__ import annotations
from core.agents import AgentRequest, AgentResponse


class StocksAgent:
    name = "stocks"
    description = "Stock price, ticker, watchlist, and market requests."
    priority = 80
    enabled = True
    _KEYWORDS = ("株", "株価", "銘柄", "ticker", "stock", "stocks", "share price")

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(keyword in text for keyword in self._KEYWORDS)

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="株価Agentを起動しました。現在は市場データ接続の準備段階です。", metadata={"feature": self.name, "status": "scaffold"})

agent = StocksAgent()

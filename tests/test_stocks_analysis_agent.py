from agents.stocks.node import StocksAgent
from core.agents import AgentRequest
from core.stocks import StockHistoryPoint
from datetime import datetime, timedelta, timezone


def test_agent_extracts_ticker_and_returns_analysis(monkeypatch):
    points = tuple(
        StockHistoryPoint(
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
            close=100 + i,
        )
        for i in range(60)
    )
    monkeypatch.setattr(StocksAgent, "_fetch_history", classmethod(lambda cls, ticker: ("USD", list(points))))

    response = StocksAgent().handle(
        AgentRequest("u", "AAPLを分析して", channel="slack")
    )

    assert response.metadata["feature"] == "stocks"
    assert response.metadata["mode"] == "analysis"
    assert response.metadata["ticker"] == "AAPL"
    assert "RSI14" in response.text
    assert "将来の値動きを保証する予測ではありません" in response.text


def test_analysis_without_ticker_is_explicit_about_required_input():
    response = StocksAgent().handle(AgentRequest("u", "テクニカル分析して"))
    assert response.metadata["mode"] == "analysis"
    assert "Ticker" in response.text


def test_agent_supports_multi_stock_comparison(monkeypatch):
    def fake_history(cls, ticker):
        base = 100.0 if ticker == "AAPL" else 110.0
        points = [
            StockHistoryPoint(
                observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
                close=base + i,
                volume=1000 + i,
            )
            for i in range(60)
        ]
        return "USD", points

    monkeypatch.setattr(StocksAgent, "_fetch_history", classmethod(fake_history))
    response = StocksAgent().handle(
        AgentRequest("u", "比較 AAPL MSFT", channel="slack")
    )
    assert response.metadata["mode"] == "compare"
    assert response.metadata["tickers"] == ("AAPL", "MSFT")
    assert "AAPL:" in response.text
    assert "MSFT:" in response.text


def test_agent_watchlist_commands(monkeypatch):
    class Watchlist:
        def __init__(self):
            self.items = []
        def add(self, user_id, ticker, label=""):
            if ticker in self.items:
                return False
            self.items.append(ticker)
            return True
        def remove(self, user_id, ticker):
            if ticker not in self.items:
                return False
            self.items.remove(ticker)
            return True
        def list_all(self, user_id):
            return [{"ticker": item, "label": ""} for item in self.items]

    watchlist = Watchlist()
    monkeypatch.setattr("agents.stocks.node.stock_watchlist", watchlist)

    agent = StocksAgent()
    add = agent.handle(AgentRequest("u", "ウォッチ追加 7203"))
    assert add.metadata["mode"] == "watch_add"
    assert "7203をウォッチリストに追加しました" in add.text

    listing = agent.handle(AgentRequest("u", "ウォッチ一覧"))
    assert listing.metadata["mode"] == "watch_list"
    assert "7203" in listing.text

    remove = agent.handle(AgentRequest("u", "ウォッチ削除 7203"))
    assert remove.metadata["mode"] == "watch_remove"

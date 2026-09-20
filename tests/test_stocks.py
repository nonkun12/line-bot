from agents.stocks.node import StocksAgent
from core.agents import AgentRequest


def test_normalize_japanese_ticker():
    assert StocksAgent.normalize_ticker("7203") == "7203.T"
    assert StocksAgent.normalize_ticker(" aapl ") == "AAPL"


def test_format_market_time_as_jst():
    # 2026-01-01 00:00:00 UTC -> 2026-01-01 09:00 JST.
    assert StocksAgent._format_market_time(1767225600) == "2026-01-01 09:00 JST"


def test_market_metadata_is_extracted_from_yahoo_payload(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'''{
                "chart": {
                    "result": [{
                        "meta": {
                            "regularMarketPrice": 123.45,
                            "previousClose": 120.00,
                            "currency": "USD",
                            "regularMarketTime": 1767225600,
                            "marketState": "CLOSED"
                        }
                    }]
                }
            }'''

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())
    quote = StocksAgent._fetch_quote("AAPL")
    assert quote["price"] == 123.45
    assert quote["change"] == 3.45
    assert quote["market_state"] == "CLOSED"
    assert quote["market_time_jst"] == "2026-01-01 09:00 JST"

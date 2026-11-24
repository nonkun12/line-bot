from agents.stocks.node import StocksAgent
from core.agents import AgentRequest
from core.stocks import StockQuote, safe_stock_quote
from core.stocks import StockQuote, safe_stock_quote


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


def test_yahoo_quote_retries_after_valid_error_payload(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.payload

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return FakeResponse(
                b'{"chart":{"result":null,"error":{"code":"Not Found","description":"not found"}}}'
            )
        return FakeResponse(
            b'''{
                "chart": {
                    "result": [{
                        "meta": {
                            "regularMarketPrice": 3025.0,
                            "previousClose": 3034.0,
                            "currency": "JPY",
                            "regularMarketTime": 1768795200,
                            "marketState": "CLOSED"
                        }
                    }]
                }
            }'''
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    quote = StocksAgent._fetch_quote("7203.T")

    assert quote["price"] == 3025.0
    assert len(calls) == 2
    assert "query1.finance.yahoo.com" in calls[0]
    assert "query2.finance.yahoo.com" in calls[1]

def test_yahoo_quote_retries_second_endpoint(monkeypatch):
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
                            "regularMarketPrice": 3025.0,
                            "previousClose": 3034.0,
                            "currency": "JPY",
                            "regularMarketTime": 1768795200,
                            "marketState": "CLOSED"
                        }
                    }]
                }
            }'''

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise OSError("temporary Yahoo failure")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    quote = StocksAgent._fetch_quote("7203.T")

    assert quote["price"] == 3025.0
    assert len(calls) == 2
    assert "query1.finance.yahoo.com" in calls[0]
    assert "query2.finance.yahoo.com" in calls[1]

def test_yahoo_japan_html_fallback(monkeypatch):
    html = """<!doctype html>
<html><body>
  <h1>トヨタ自動車(株)〖7203.T〗</h1>
  <div>3,025</div>
  <div>前日比</div>
  <div>-9(-0.30%)</div>
  <div>リアルタイム株価</div>
</body></html>"""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return html.encode("utf-8")

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.startswith("https://query"):
            raise OSError("Yahoo chart unavailable")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    quote = StocksAgent._fetch_quote("7203.T")

    assert quote["price"] == 3025.0
    assert quote["change"] == -9.0
    assert quote["change_pct"] == -0.30
    assert quote["currency"] == "JPY"
    assert calls[-1] == "https://finance.yahoo.co.jp/quote/7203.T"



def test_safe_stock_quote_validates_provider_output_and_normalizes_ticker():
    class FakeProvider:
        def __init__(self, quote=None, error=None):
            self.quote = quote
            self.error = error
            self.requested = []

        def get_quote(self, ticker):
            self.requested.append(ticker)
            if self.error is not None:
                raise self.error
            return self.quote

    valid_quote = StockQuote(ticker="7203.T", price=100.0, currency="JPY")
    valid_provider = FakeProvider(valid_quote)
    assert safe_stock_quote(valid_provider, " 7203 ") == valid_quote
    assert valid_provider.requested == ["7203.T"]

    mismatched_provider = FakeProvider(
        StockQuote(ticker="AAPL", price=100.0, currency="USD")
    )
    assert safe_stock_quote(mismatched_provider, "7203") is None

    negative_price_provider = FakeProvider(
        StockQuote(ticker="7203.T", price=-1.0, currency="JPY")
    )
    assert safe_stock_quote(negative_price_provider, "7203") is None

    malformed_provider = FakeProvider("not-a-StockQuote")
    assert safe_stock_quote(malformed_provider, "7203") is None

    failing_provider = FakeProvider(error=RuntimeError("provider unavailable"))
    assert safe_stock_quote(failing_provider, "7203") is None

    empty_provider = FakeProvider(valid_quote)
    assert safe_stock_quote(empty_provider, "   ") is None
    assert empty_provider.requested == []


def test_safe_stock_quote_normalizes_and_rejects_invalid_provider_responses():
    class FakeProvider:
        def __init__(self, result=None, error=None):
            self.result = result
            self.error = error
            self.requested = []

        def get_quote(self, ticker):
            self.requested.append(ticker)
            if self.error is not None:
                raise self.error
            return self.result

    valid = StockQuote(ticker="7203.T", price=3000.0, currency="JPY")
    provider = FakeProvider(result=valid)
    assert safe_stock_quote(provider, " 7203 ") is valid
    assert provider.requested == ["7203.T"]

    assert safe_stock_quote(FakeProvider(result=object()), "7203") is None
    mismatched = StockQuote(ticker="AAPL", price=3000.0, currency="USD")
    assert safe_stock_quote(FakeProvider(result=mismatched), "7203") is None
    negative = StockQuote(ticker="7203.T", price=-1.0, currency="JPY")
    assert safe_stock_quote(FakeProvider(result=negative), "7203") is None
    assert safe_stock_quote(FakeProvider(error=RuntimeError("provider failure")), "7203") is None

    empty = FakeProvider(result=valid)
    assert safe_stock_quote(empty, "   ") is None
    assert empty.requested == []

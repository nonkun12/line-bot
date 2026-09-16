from datetime import datetime, timezone

from core.stocks import StockQuote, normalize_stock_ticker, safe_stock_quote


class Provider:
    def __init__(self, quote):
        self.quote = quote
        self.calls = []

    def get_quote(self, ticker):
        self.calls.append(ticker)
        return self.quote


def test_normalize_stock_ticker_supports_japanese_and_global_symbols():
    assert normalize_stock_ticker("7203") == "7203.T"
    assert normalize_stock_ticker(" aapl ") == "AAPL"


def test_safe_stock_quote_normalizes_and_validates_provider_output():
    provider = Provider(
        StockQuote(
            ticker="7203.T",
            price=3512.5,
            currency="JPY",
            observed_at=datetime.now(timezone.utc),
        )
    )

    quote = safe_stock_quote(provider, "7203")

    assert quote is not None
    assert quote.display_ticker == "7203"
    assert provider.calls == ["7203.T"]


def test_safe_stock_quote_fails_closed_on_provider_errors_and_bad_data():
    error_provider = Provider(None)

    def raising_get_quote(_ticker):
        raise RuntimeError("provider unavailable")

    error_provider.get_quote = raising_get_quote
    assert safe_stock_quote(error_provider, "7203") is None

    bad_provider = Provider(StockQuote(ticker="7203.T", price=-1))
    assert safe_stock_quote(bad_provider, "7203") is None

    mismatch_provider = Provider(StockQuote(ticker="AAPL", price=100))
    assert safe_stock_quote(mismatch_provider, "7203") is None

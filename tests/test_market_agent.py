from __future__ import annotations

from agents.market.intents import is_market_intent
from agents.market.node import MarketAgent
from core.agents import AgentRequest


def test_market_intent_detects_dow_and_fx() -> None:
    assert is_market_intent("NYダウを教えて")
    assert is_market_intent("ドル円の為替")
    assert is_market_intent("what is the forex rate?")
    assert is_market_intent("S&P500を教えて")
    assert is_market_intent("日経225を教えて")
    assert is_market_intent("DAXを教えて")


def test_market_agent_summary_includes_dow_and_major_fx(monkeypatch) -> None:
    def fake_quote(cls, ticker: str):
        prices = {
            "^DJI": 42000.0,
            "JPY=X": 150.123,
            "EURUSD=X": 1.1234,
            "GBPUSD=X": 1.3344,
            "AUDUSD=X": 0.6677,
            "EURJPY=X": 168.234,
            "GBPJPY=X": 200.345,
            "CHF=X": 0.8123,
            "CAD=X": 1.3789,
            "USDCNY=X": 7.1234,
            "^GSPC": 5100.0,
            "^IXIC": 18000.0,
            "^N225": 40000.0,
            "^GDAXI": 20000.0,
            "^FTSE": 8200.0,
            "^HSI": 20000.0,
            "000001.SS": 3300.0,
            "^KS11": 2700.0,
        }
        return {
            "price": prices[ticker],
            "previous_close": prices[ticker] - 1,
            "change": 1.0,
            "change_pct": 0.1,
            "currency": "USD",
            "market_time_jst": "2026-09-18 20:00 JST",
            "market_state": "REGULAR",
        }

    monkeypatch.setattr(MarketAgent, "_fetch_quote", classmethod(fake_quote))

    response = MarketAgent().handle(
        AgentRequest(user_id="u1", message="NYダウと主要な為替を教えて", channel="slack")
    )

    assert response.metadata["status"] == "online"
    assert response.metadata["mode"] == "summary"
    assert "NYダウ: 42000.00" in response.text
    assert "USD/JPY: 150.123" in response.text
    assert "EUR/USD: 1.1234" in response.text
    assert "USD/CNY: 7.1234" in response.text
    assert "S&P500" in response.text
    assert "NASDAQ総合" in response.text
    assert "日経225" in response.text
    assert "DAX" in response.text
    assert "FTSE100" in response.text


def test_market_agent_fx_mode_omits_dow(monkeypatch) -> None:
    def fake_quote(cls, ticker: str):
        assert ticker != "^DJI"
        return {
            "price": 150.0,
            "previous_close": 149.0,
            "change": 1.0,
            "change_pct": 0.67,
            "currency": "JPY",
            "market_time_jst": "2026-09-18 20:00 JST",
            "market_state": "REGULAR",
        }

    monkeypatch.setattr(MarketAgent, "_fetch_quote", classmethod(fake_quote))

    response = MarketAgent().handle(
        AgentRequest(user_id="u1", message="ドル円の為替", channel="slack")
    )

    assert response.metadata["mode"] == "fx"
    assert "NYダウ" not in response.text
    assert "USD/JPY: 150.000" in response.text


def test_market_agent_fails_closed_on_data_error(monkeypatch) -> None:
    def broken_quote(cls, ticker: str):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(MarketAgent, "_fetch_quote", classmethod(broken_quote))

    response = MarketAgent().handle(
        AgentRequest(user_id="u1", message="NYダウ", channel="slack")
    )

    assert response.metadata["status"] == "degraded"
    assert "推測して表示することはしません" in response.text


def test_market_quote_keys_target_specific_instruments() -> None:
    from agents.market.intents import market_quote_keys

    assert market_quote_keys("S&P500と日経225") == ("sp500", "nikkei")
    assert market_quote_keys("ドル円だけ教えて") == ("usd_jpy",)
    assert set(market_quote_keys("主要な為替")) == {
        "usd_jpy", "eur_usd", "gbp_usd", "aud_usd", "eur_jpy",
        "gbp_jpy", "usd_chf", "usd_cad", "usd_cny",
    }


def test_market_agent_fetches_only_requested_quotes(monkeypatch) -> None:
    seen: list[str] = []

    def fake_quote(cls, ticker: str):
        seen.append(ticker)
        return {
            "price": 100.0,
            "previous_close": 99.0,
            "change": 1.0,
            "change_pct": 1.01,
            "currency": "USD",
            "market_time_jst": "2026-09-18 20:00 JST",
            "market_state": "REGULAR",
        }

    monkeypatch.setattr(MarketAgent, "_fetch_quote", classmethod(fake_quote))
    response = MarketAgent().handle(
        AgentRequest(user_id="u1", message="S&P500だけ", channel="slack")
    )

    assert seen == ["^GSPC"]
    assert response.metadata["mode"] == "quotes"
    assert response.metadata["requested_instruments"] == ["sp500"]
    assert "S&P500: 100.000" in response.text
    assert "日経225" not in response.text
    assert "USD/JPY" not in response.text

import base64
from unittest.mock import patch

import pytest

from app import app
from routes.dashboard import _normalize_stock_dashboard_tickers

TEST_USER_ID = "U19391b0b93be2f4d94284361153919ce"


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    monkeypatch.setenv("DASHBOARD_OWNER_USER_ID", TEST_USER_ID)
    token = base64.b64encode(b"testuser:testpass").decode()
    return {"Authorization": "Basic " + token}


def test_stock_dashboard_page(auth_headers):
    client = app.test_client()
    response = client.get("/stock-dashboard", headers=auth_headers)
    assert response.status_code == 200
    assert "株式投資ダッシュボード".encode() in response.data
    assert b"/api/stock-dashboard/analyze" in response.data


def test_stock_dashboard_ticker_normalization_is_bounded():
    assert _normalize_stock_dashboard_tickers("7203, 6758 9984, AAPL") == [
        "7203.T", "6758.T", "9984.T", "AAPL"
    ]
    assert _normalize_stock_dashboard_tickers("7203,7203,invalid!") == ["7203.T"]
    assert len(_normalize_stock_dashboard_tickers(" ".join(["7203"] * 10))) == 1


def test_stock_dashboard_analysis_returns_sorted_results(auth_headers):
    client = app.test_client()
    payloads = {
        "7203.T": {"ticker": "7203", "signal_score": 1, "signal": "HOLD"},
        "6758.T": {"ticker": "6758", "signal_score": 4, "signal": "BUY"},
    }

    def fake_analyze(ticker):
        return {
            **payloads[ticker],
            "symbol": ticker,
            "price": 1000,
            "previous_close": 990,
            "change": 10,
            "change_pct": 1.01,
            "currency": "JPY",
            "market_state": "CLOSED",
            "market_time_jst": "2026-09-23 07:00 JST",
            "trend": "bullish",
            "rsi14": 55.0,
            "macd": 1.0,
            "macd_signal": 0.5,
            "sma20": 1000.0,
            "sma50": 980.0,
            "volatility20": 20.0,
            "bollinger_mid20": 990.0,
            "bollinger_upper20": 1030.0,
            "bollinger_lower20": 950.0,
            "data_source": "Yahoo Finance",
        }

    with patch("routes.dashboard._analyze_stock_dashboard_ticker", side_effect=fake_analyze):
        response = client.post(
            "/api/stock-dashboard/analyze",
            json={"tickers": ["7203", "6758"]},
            headers=auth_headers,
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [x["ticker"] for x in data["results"]] == ["6758", "7203"]
    assert data["results"][0]["signal"] == "BUY"
    assert data["limits"]["max_tickers"] == 6


def test_stock_dashboard_analysis_reports_fetch_errors(auth_headers):
    client = app.test_client()
    with patch("routes.dashboard._analyze_stock_dashboard_ticker", side_effect=RuntimeError("down")):
        response = client.post(
            "/api/stock-dashboard/analyze",
            json={"tickers": ["7203"]},
            headers=auth_headers,
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["results"] == []
    assert data["errors"] == [{"ticker": "7203", "error": "market data unavailable"}]


def test_stock_dashboard_analysis_requires_ticker(auth_headers):
    client = app.test_client()
    response = client.post("/api/stock-dashboard/analyze", json={"tickers": []}, headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["error"] == "ticker is required"


def test_stock_dashboard_requires_auth():
    client = app.test_client()
    response = client.get("/stock-dashboard")
    assert response.status_code == 401

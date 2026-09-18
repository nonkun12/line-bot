"""Global market and FX AI agent using Yahoo Finance market data."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agents.market.intents import is_market_intent
from core.agents import AgentRequest, AgentResponse


_DEFAULT_TIMEOUT_SEC = 8
_JST = ZoneInfo("Asia/Tokyo")

_INSTRUMENTS = {
    "dow": {"ticker": "^DJI", "label": "NYダウ", "kind": "index"},
    "usd_jpy": {"ticker": "JPY=X", "label": "USD/JPY", "kind": "fx"},
    "eur_usd": {"ticker": "EURUSD=X", "label": "EUR/USD", "kind": "fx"},
    "gbp_usd": {"ticker": "GBPUSD=X", "label": "GBP/USD", "kind": "fx"},
    "aud_usd": {"ticker": "AUDUSD=X", "label": "AUD/USD", "kind": "fx"},
    "eur_jpy": {"ticker": "EURJPY=X", "label": "EUR/JPY", "kind": "fx"},
    "gbp_jpy": {"ticker": "GBPJPY=X", "label": "GBP/JPY", "kind": "fx"},
    "usd_chf": {"ticker": "CHF=X", "label": "USD/CHF", "kind": "fx"},
    "usd_cad": {"ticker": "CAD=X", "label": "USD/CAD", "kind": "fx"},
    "usd_cny": {"ticker": "USDCNY=X", "label": "USD/CNY", "kind": "fx"},
}


class MarketAgent:
    name = "global_market"
    description = "NY Dow, major global currency pairs, and market summary."
    priority = 82
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_market_intent(request.message)

    @staticmethod
    def _format_market_time(value: object) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc).astimezone(_JST)
        except (OverflowError, OSError, ValueError):
            return None
        return dt.strftime("%Y-%m-%d %H:%M JST")

    @classmethod
    def _fetch_quote(cls, ticker: str) -> dict[str, object]:
        encoded = urllib.parse.quote(ticker, safe=".")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1d&interval=1m"
        req = urllib.request.Request(url, headers={"User-Agent": "LINE-AI-Secretary/1.0"})
        with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))

        result = payload.get("chart", {}).get("result")
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            raise ValueError("quote result unavailable")
        data = result[0]
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        price = meta.get("regularMarketPrice")
        previous = meta.get("previousClose")
        if not isinstance(price, (int, float)):
            indicators = data.get("indicators", {})
            quotes = indicators.get("quote", []) if isinstance(indicators, dict) else []
            closes = quotes[0].get("close", []) if quotes and isinstance(quotes[0], dict) else []
            numeric_closes = [v for v in closes if isinstance(v, (int, float))]
            price = numeric_closes[-1] if numeric_closes else None
        if not isinstance(price, (int, float)):
            raise ValueError("quote price unavailable")

        change = price - previous if isinstance(previous, (int, float)) else None
        change_pct = (change / previous * 100) if change is not None and previous else None
        return {
            "price": float(price),
            "previous_close": float(previous) if isinstance(previous, (int, float)) else None,
            "change": round(float(change), 10) if change is not None else None,
            "change_pct": round(float(change_pct), 10) if change_pct is not None else None,
            "currency": str(meta.get("currency") or ""),
            "market_time_jst": cls._format_market_time(meta.get("regularMarketTime")),
            "market_state": str(meta.get("marketState") or "").upper() or None,
        }

    @staticmethod
    def _mode(message: str) -> str:
        value = (message or "").casefold()
        if any(term in value for term in ("為替", "ドル円", "ユーロドル", "ポンドドル", "豪ドル", "ユーロ円", "ポンド円", "ドルスイス", "ドルカナダ", "ドル人民元", "通貨", "forex", "fx", "exchange rate", "currency", "currencies")):
            if "ダウ" not in value and "世界株価" not in value and "世界の株価" not in value and "dow" not in value:
                return "fx"
        if any(term in value for term in ("世界", "市場", "マーケット", "nyダウ", "ダウ", "dow")):
            return "summary"
        return "summary"

    @classmethod
    def _render_quote(cls, label: str, quote: dict[str, object]) -> str:
        price = quote["price"]
        change = quote.get("change")
        change_pct = quote.get("change_pct")
        currency = str(quote.get("currency") or "")
        if label in {"USD/JPY", "EUR/JPY", "GBP/JPY"}:
            price_text = f"{float(price):.3f}"
        else:
            price_text = f"{float(price):.4f}" if "USD/" in label or "/USD" in label else f"{float(price):.3f}"
        suffix = f" {currency}" if currency else ""
        line = f"{label}: {price_text}{suffix}"
        if isinstance(change, (int, float)):
            sign = "+" if change >= 0 else ""
            line += f" ({sign}{change:.4f}, {sign}{float(change_pct):.2f}%)" if isinstance(change_pct, (int, float)) else f" ({sign}{change:.4f})"
        return line

    @classmethod
    def _fetch_all(cls, keys: tuple[str, ...]) -> dict[str, dict[str, object]]:
        return {key: cls._fetch_quote(_INSTRUMENTS[key]["ticker"]) for key in keys}

    def handle(self, request: AgentRequest) -> AgentResponse:
        mode = self._mode(request.message)
        keys = ("usd_jpy", "eur_usd", "gbp_usd", "aud_usd", "eur_jpy", "gbp_jpy", "usd_chf", "usd_cad", "usd_cny")
        if mode == "summary":
            keys = ("dow",) + keys

        try:
            quotes = self._fetch_all(keys)
        except Exception:
            return AgentResponse(
                text=(
                    "🌎 Market AIを起動しましたが、市場データを取得できませんでした。\n"
                    "Yahoo Financeのデータ源が一時的に利用できない可能性があります。\n"
                    "価格を推測して表示することはしません。"
                ),
                metadata={"feature": self.name, "status": "degraded", "mode": mode},
            )

        lines = ["🌎 世界市場AI"]
        if "dow" in keys:
            dow = quotes["dow"]
            lines.append(f"NYダウ: {dow['price']:.2f}")
            if isinstance(dow.get("change_pct"), (int, float)):
                sign = "+" if dow["change_pct"] >= 0 else ""
                lines.append(f"前日比: {sign}{dow['change_pct']:.2f}%")
        if mode == "summary":
            lines.append("")
            lines.append("主要為替")
        for key in keys:
            if key == "dow":
                continue
            item = _INSTRUMENTS[key]
            lines.append(cls._render_quote(item["label"], quotes[key]))
        latest = next(
            (quotes[key].get("market_time_jst") for key in keys if quotes[key].get("market_time_jst")),
            None,
        )
        if latest:
            lines.append(f"基準時刻: {latest}")
        lines.append("市場データ: Yahoo Finance")

        return AgentResponse(
            text="\n".join(lines),
            metadata={
                "feature": self.name,
                "status": "online",
                "mode": mode,
                "instruments": [item["ticker"] for item in (_INSTRUMENTS[key] for key in keys)],
                "quotes": quotes,
            },
        )


agent = MarketAgent()

"""Stock-query agent with real market-data retrieval and safe fallback."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agents.stocks.intents import is_stock_intent
from core.agents import AgentRequest, AgentResponse


_TICKER_RE = re.compile(r"(?:銘柄|ticker|コード)\s*[:：]?\s*([A-Za-z]{1,6}[.]?[A-Za-z]{0,3}|\d{4})", re.IGNORECASE)
_NATURAL_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{3,6}(?:\.[A-Za-z]{1,3})?|\d{4})"
    r"(?=\s*(?:の)?\s*(?:株価|株|price))",
    re.IGNORECASE,
)
_COMPANY_TICKERS = (
    (re.compile(r"(?:トヨタ(?:自動車)?|toyota)", re.IGNORECASE), "7203.T", "トヨタ"),
)
_DEFAULT_TIMEOUT_SEC = 8
_JST = ZoneInfo("Asia/Tokyo")

_MARKET_STATE_LABELS = {
    "REGULAR": "取引時間中",
    "PRE": "取引前",
    "POST": "取引後",
    "CLOSED": "休場中",
}


class StocksAgent:
    name = "stocks"
    description = "Stock price, ticker, watchlist, and market requests."
    priority = 80
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_stock_intent(request.message)

    @staticmethod
    def normalize_ticker(raw_ticker: str) -> str:
        ticker = raw_ticker.strip().upper()
        if ticker.isdigit() and len(ticker) == 4:
            return f"{ticker}.T"
        return ticker

    @staticmethod
    def _display_ticker(ticker: str) -> str:
        return ticker[:-2] if ticker.endswith(".T") else ticker

    @classmethod
    def _resolve_ticker(cls, message: str) -> tuple[str, str] | None:
        match = _TICKER_RE.search(message) or _NATURAL_TICKER_RE.search(message)
        if match:
            ticker = cls.normalize_ticker(match.group(1))
            return ticker, cls._display_ticker(ticker)
        for pattern, ticker, label in _COMPANY_TICKERS:
            if pattern.search(message):
                return ticker, label
        return None

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
        urls = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d",
        )
        last_error: Exception | None = None

        for url in urls:
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "LINE-AI-Secretary/1.0"},
                )
                with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT_SEC) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue

            try:
                if not isinstance(payload, dict):
                    raise ValueError("quote payload unavailable")

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
                change = round(change, 10) if change is not None else None
                change_pct = (change / previous * 100) if change is not None and previous else None
                change_pct = round(change_pct, 10) if change_pct is not None else None
                currency = str(meta.get("currency") or "")
                market_time = meta.get("regularMarketTime")
                market_state = str(meta.get("marketState") or "").upper() or None
                return {
                    "ticker": cls._display_ticker(ticker),
                    "price": float(price),
                    "previous_close": float(previous) if isinstance(previous, (int, float)) else None,
                    "change": float(change) if change is not None else None,
                    "change_pct": float(change_pct) if change_pct is not None else None,
                    "currency": currency,
                    "market_time": market_time,
                    "market_time_jst": cls._format_market_time(market_time),
                    "market_state": market_state,
                }
            except (TypeError, ValueError, KeyError, IndexError) as exc:
                last_error = exc
                continue

        if ticker.endswith(".T"):
            try:
                return cls._fetch_yahoo_japan_quote(ticker)
            except (OSError, UnicodeError, ValueError) as exc:
                last_error = exc

        raise RuntimeError("Yahoo Finance quote retrieval failed") from last_error


    @staticmethod
    def _extract_visible_text(html: str) -> list[str]:
        class _Parser(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.parts = []
                self.skip = 0

            def handle_starttag(self, tag, attrs) -> None:
                if tag.lower() in {"script", "style", "noscript"}:
                    self.skip += 1

            def handle_endtag(self, tag) -> None:
                if tag.lower() in {"script", "style", "noscript"} and self.skip:
                    self.skip -= 1

            def handle_data(self, data: str) -> None:
                if not self.skip:
                    value = " ".join(data.split())
                    if value:
                        self.parts.append(value)

        parser = _Parser()
        parser.feed(html)
        parser.close()
        return parser.parts

    @classmethod
    def _fetch_yahoo_japan_quote(cls, ticker: str) -> dict[str, object]:
        if not ticker.endswith(".T"):
            raise ValueError("Yahoo Finance Japan fallback supports TSE tickers only")

        encoded = urllib.parse.quote(ticker, safe=".")
        url = f"https://finance.yahoo.co.jp/quote/{encoded}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "LINE-AI-Secretary/1.0"},
        )
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT_SEC) as response:
            html = response.read().decode("utf-8", errors="replace")

        tokens = cls._extract_visible_text(html)
        try:
            idx = tokens.index("前日比")
        except ValueError as exc:
            raise ValueError("Yahoo Finance Japan quote marker unavailable") from exc

        if idx == 0:
            raise ValueError("Yahoo Finance Japan quote price unavailable")

        price_text = tokens[idx - 1].replace(",", "")
        if not price_text.replace(".", "", 1).isdigit():
            raise ValueError("Yahoo Finance Japan quote price unavailable")

        change = None
        change_pct = None
        if idx + 1 < len(tokens):
            value = tokens[idx + 1].replace(",", "")
            parts = value.rstrip(")").split("(")
            if len(parts) == 2 and parts[0].replace("-", "", 1).replace(".", "", 1).isdigit():
                pct_text = parts[1].rstrip("%")
                if pct_text.replace("-", "", 1).replace(".", "", 1).isdigit():
                    change = float(parts[0])
                    change_pct = float(pct_text)

        price = float(price_text)
        return {
            "ticker": cls._display_ticker(ticker),
            "price": price,
            "previous_close": price - change if change is not None else None,
            "change": change,
            "change_pct": change_pct,
            "currency": "JPY",
            "market_time": None,
            "market_time_jst": None,
            "market_state": None,
        }

    def handle(self, request: AgentRequest) -> AgentResponse:
        resolved = self._resolve_ticker(request.message)
        if not resolved:
            return AgentResponse(
                text=(
                    "📈 株価Agentを起動しました。\n\n"
                    "銘柄コードまたはTickerを含めて送ってください。"
                    "例: 「トヨタの株価」「銘柄 7203」「ticker AAPL」\n"
                    "実データ取得に対応しています。"
                ),
                metadata={"feature": self.name, "status": "online", "ticker": None},
            )

        ticker, display_name = resolved
        try:
            quote = self._fetch_quote(ticker)
        except Exception:
            return AgentResponse(
                text=(
                    f"📈 {display_name}（{self._display_ticker(ticker)}）の株価を取得できませんでした。\n"
                    "市場データ源が一時的に利用できない可能性があります。\n"
                    "価格を推測して表示することはしません."
                ),
                metadata={"feature": self.name, "status": "degraded", "ticker": self._display_ticker(ticker)},
            )

        currency = quote["currency"] or ""
        unit = f" {currency}" if currency else ""
        change = quote["change"]
        change_pct = quote["change_pct"]
        change_text = ""
        if isinstance(change, (int, float)):
            sign = "+" if change >= 0 else ""
            change_text = f"\n前日比: {sign}{change:.2f}{unit}"
            if isinstance(change_pct, (int, float)):
                change_text += f" ({sign}{change_pct:.2f}%)"
        market_state = quote.get("market_state")
        state_label = _MARKET_STATE_LABELS.get(str(market_state), "")
        state_text = f"\n市場状態: {state_label}" if state_label else ""
        time_text = f"\n基準時刻: {quote['market_time_jst']}" if quote.get("market_time_jst") else ""

        return AgentResponse(
            text=(
                f"📈 {display_name}（{quote['ticker']}）\n"
                f"現在値: {quote['price']:.2f}{unit}"
                f"{change_text}{state_text}{time_text}\n"
                "市場データ: Yahoo Finance"
            ),
            metadata={"feature": self.name, "status": "online", "company": display_name, **quote},
        )


agent = StocksAgent()

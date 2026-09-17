"""Stock-query agent with real market-data retrieval and safe fallback."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agents.stocks.intents import is_stock_intent
from core.agents import AgentRequest, AgentResponse
from core.stocks import StockHistoryPoint, analyze_history, compare_analyses
import stock_watchlist


_TICKER_RE = re.compile(
    r"(?:銘柄|ticker|コード)\s*[:：]?\s*([A-Za-z]{1,6}[.]?[A-Za-z]{0,3}|\d{4})",
    re.IGNORECASE,
)
_NATURAL_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{3,6}(?:\.[A-Za-z]{1,3})?|\d{4})"
    r"(?=\s*(?:の)?\s*(?:株価|株|price))",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"(比較|compare)\s+(.+)", re.IGNORECASE)
_ANALYSIS_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,6}(?:\.[A-Za-z]{1,3})?|\d{4})"
    r"\s*(?:の|を)?\s*(?:分析|テクニカル|指標|チャート|analy(?:ze|sis)|technical)",
    re.IGNORECASE,
)
_DEFAULT_TIMEOUT_SEC = 8
_HISTORY_TIMEOUT_SEC = 10
_JST = ZoneInfo("Asia/Tokyo")


_MARKET_STATE_LABELS = {
    "REGULAR": "取引時間中",
    "PRE": "取引前",
    "POST": "取引後",
    "CLOSED": "休場中",
}


class StocksAgent:
    name = "stocks"
    description = "Stock price, ticker, technical analysis, watchlist, and market requests."
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
        request = urllib.request.Request(url, headers={"User-Agent": "LINE-AI-Secretary/1.0"})
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT_SEC) as response:
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

    @classmethod
    def _fetch_history(cls, ticker: str) -> tuple[str, list[StockHistoryPoint]]:
        encoded = urllib.parse.quote(ticker, safe=".")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            "?range=6mo&interval=1d&events=history"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "LINE-AI-Secretary/1.0"})
        with urllib.request.urlopen(request, timeout=_HISTORY_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))

        result = payload.get("chart", {}).get("result")
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            raise ValueError("history result unavailable")
        data = result[0]
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        timestamps = data.get("timestamp")
        indicators = data.get("indicators")
        quotes = indicators.get("quote", []) if isinstance(indicators, dict) else []
        quote = quotes[0] if quotes and isinstance(quotes[0], dict) else {}
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        if not isinstance(timestamps, list) or not isinstance(closes, list):
            raise ValueError("history series unavailable")

        points: list[StockHistoryPoint] = []
        for index, timestamp in enumerate(timestamps):
            close = closes[index] if index < len(closes) else None
            if not isinstance(timestamp, (int, float)) or not isinstance(close, (int, float)) or close <= 0:
                continue
            volume = volumes[index] if isinstance(volumes, list) and index < len(volumes) else None
            points.append(
                StockHistoryPoint(
                    observed_at=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                    close=float(close),
                    volume=int(volume) if isinstance(volume, (int, float)) else None,
                )
            )
        if not points:
            raise ValueError("history has no valid points")
        currency = str(meta.get("currency") or "")
        return currency, points

    @classmethod
    def _comparison_reply(cls, comparison) -> str:
        lines = ["📊 株価AI・複数銘柄比較"]
        for analysis in comparison.analyses:
            ret = f"{analysis.return_20d_pct:+.2f}%" if analysis.return_20d_pct is not None else "データ不足"
            rsi = f"{analysis.rsi_14:.1f}" if analysis.rsi_14 is not None else "-"
            vol = f"{analysis.volatility_20_annualized_pct:.1f}%" if analysis.volatility_20_annualized_pct is not None else "-"
            lines.append(
                f"{cls._display_ticker(analysis.ticker)}: 20日リターン {ret} / RSI14 {rsi} / 年率ボラ {vol}"
            )
        lines.append("")
        lines.append("※同じ観測指標を横並びにした記述的比較です。投資判断や将来リターンを示すものではありません。")
        lines.append("市場データ: Yahoo Finance")
        return "\n".join(lines)

    @classmethod
    def _analysis_reply(cls, analysis, currency: str) -> str:
        unit = f" {currency}" if currency else ""
        lines = [
            f"📊 {cls._display_ticker(analysis.ticker)} テクニカル分析",
            f"基準値: {analysis.latest_close:.2f}{unit}",
            f"観測日数: {analysis.data_points}日",
        ]
        if analysis.return_20d_pct is not None:
            lines.append(f"20営業日リターン: {analysis.return_20d_pct:+.2f}%")
        if analysis.sma_20 is not None:
            lines.append(f"SMA20: {analysis.sma_20:.2f}{unit}")
        if analysis.sma_50 is not None:
            lines.append(f"SMA50: {analysis.sma_50:.2f}{unit}")
        if analysis.rsi_14 is not None:
            lines.append(f"RSI14: {analysis.rsi_14:.2f}")
        if analysis.volatility_20_annualized_pct is not None:
            lines.append(f"20日年率換算ボラティリティ: {analysis.volatility_20_annualized_pct:.2f}%")
        if analysis.high_20 is not None and analysis.low_20 is not None:
            lines.append(f"20日高値/安値: {analysis.high_20:.2f}{unit} / {analysis.low_20:.2f}{unit}")
        if analysis.latest_volume is not None:
            lines.append(f"直近出来高: {analysis.latest_volume:,}")
        if analysis.average_volume_20 is not None:
            lines.append(f"20日平均出来高: {analysis.average_volume_20:,.0f}")
        if analysis.volume_ratio_20 is not None:
            lines.append(f"出来高比率（直近/20日平均）: {analysis.volume_ratio_20:.2f}x")
        lines.append("")
        lines.append("※観測済み市場データから算出した記述的指標です。将来の値動きを保証する予測ではありません。")
        lines.append("市場データ: Yahoo Finance")
        return "\n".join(lines)

    def handle(self, request: AgentRequest) -> AgentResponse:
        original = request.message.strip()

        watch_add = re.search(
            r"(?:ウォッチ(?:リスト)?\s*(?:に)?\s*(?:追加|登録)|watch\s*add)\s+(.+)$",
            original,
            re.IGNORECASE,
        )
        if watch_add:
            ticker_match = re.search(
                r"(?<![A-Za-z0-9])(?:\d{4}|[A-Za-z]{2,6}(?:\.[A-Za-z]{1,3})?)(?![A-Za-z0-9])",
                watch_add.group(1),
            )
            if not ticker_match:
                return AgentResponse(
                    text="📋 ウォッチ追加にはTickerまたは4桁銘柄コードを指定してください。",
                    metadata={"feature": self.name, "status": "online", "mode": "watch_add"},
                )
            ticker = self.normalize_ticker(ticker_match.group(0))
            label = watch_add.group(1).replace(ticker_match.group(0), "").strip(" ：:()")
            added = stock_watchlist.add(request.user_id, ticker, label)
            return AgentResponse(
                text=f"📌 {self._display_ticker(ticker)}をウォッチリストに{'追加しました' if added else '登録済みです'}。",
                metadata={"feature": self.name, "status": "online", "mode": "watch_add", "ticker": self._display_ticker(ticker)},
            )

        if re.search(r"^(?:ウォッチ(?:リスト)?\s*(?:一覧|確認)|watch\s*list)$", original, re.IGNORECASE):
            items = stock_watchlist.list_all(request.user_id)
            if not items:
                return AgentResponse(
                    text="📋 ウォッチリストは空です。例: 「ウォッチ追加 7203」",
                    metadata={"feature": self.name, "status": "online", "mode": "watch_list", "count": 0},
                )
            lines = ["📋 株価ウォッチリスト"]
            for item in items:
                label = f" ({item['label']})" if item.get("label") else ""
                lines.append(f"- {self._display_ticker(item['ticker'])}{label}")
            return AgentResponse(
                text="\n".join(lines),
                metadata={"feature": self.name, "status": "online", "mode": "watch_list", "count": len(items)},
            )

        watch_remove = re.search(
            r"(?:ウォッチ(?:リスト)?\s*(?:から)?\s*(?:削除|解除)|watch\s*remove)\s+(.+)$",
            original,
            re.IGNORECASE,
        )
        if watch_remove:
            ticker_match = re.search(
                r"(?<![A-Za-z0-9])(?:\d{4}|[A-Za-z]{2,6}(?:\.[A-Za-z]{1,3})?)(?![A-Za-z0-9])",
                watch_remove.group(1),
            )
            if not ticker_match:
                return AgentResponse(
                    text="📋 ウォッチ削除にはTickerまたは4桁銘柄コードを指定してください。",
                    metadata={"feature": self.name, "status": "online", "mode": "watch_remove"},
                )
            ticker = self.normalize_ticker(ticker_match.group(0))
            removed = stock_watchlist.remove(request.user_id, ticker)
            return AgentResponse(
                text=f"📌 {self._display_ticker(ticker)}をウォッチリストから{'削除しました' if removed else '見つけられませんでした'}。",
                metadata={"feature": self.name, "status": "online", "mode": "watch_remove", "ticker": self._display_ticker(ticker)},
            )

        compare_match = _COMPARE_RE.search(original)
        if compare_match:
            raw_symbols = re.findall(
                r"(?<![A-Za-z0-9])(?:\d{4}|[A-Za-z]{2,6}(?:\.[A-Za-z]{1,3})?)(?![A-Za-z0-9])",
                compare_match.group(2),
            )
            tickers = tuple(dict.fromkeys(self.normalize_ticker(value) for value in raw_symbols))[:5]
            if len(tickers) < 2:
                return AgentResponse(
                    text="📊 複数銘柄比較には2〜5銘柄を指定してください。例: 「比較 AAPL MSFT GOOGL」",
                    metadata={"feature": self.name, "status": "online", "mode": "compare", "tickers": tickers},
                )
            analyses = []
            for ticker in tickers:
                try:
                    _currency, history = self._fetch_history(ticker)
                    analysis = analyze_history(ticker, history)
                except Exception:
                    analysis = None
                if analysis is not None:
                    analyses.append(analysis)
            if len(analyses) < 2:
                return AgentResponse(
                    text="📊 比較に必要な履歴データを2銘柄以上取得できませんでした。価格を推測して比較することはしません。",
                    metadata={"feature": self.name, "status": "degraded", "mode": "compare", "tickers": tickers},
                )
            comparison = compare_analyses(analyses)
            return AgentResponse(
                text=self._comparison_reply(comparison),
                metadata={"feature": self.name, "status": "online", "mode": "compare", "tickers": tickers},
            )

        wants_analysis = bool(_ANALYSIS_TICKER_RE.search(original) or any(
            token in original.casefold()
            for token in ("テクニカル", "チャート", "分析して", "technical analysis")
        ))

        match = _TICKER_RE.search(original)
        if not match:
            match = _NATURAL_TICKER_RE.search(original)
        if not match and wants_analysis:
            match = _ANALYSIS_TICKER_RE.search(original)
        if not match:
            mode_text = "分析" if wants_analysis else "株価取得"
            return AgentResponse(
                text=(
                    f"📈 株価AIの{mode_text}モードです。\n\n"
                    "銘柄コードまたはTickerを含めて送ってください。"
                    "例: 「銘柄 7203」「ticker AAPL」「AAPLの株価」「7203の分析」"
                ),
                metadata={"feature": self.name, "status": "online", "ticker": None, "mode": "analysis" if wants_analysis else "quote"},
            )

        requested = match.group(1)
        ticker = self.normalize_ticker(requested)

        if wants_analysis:
            try:
                currency, history = self._fetch_history(ticker)
                analysis = analyze_history(ticker, history)
                if analysis is None:
                    raise ValueError("analysis unavailable")
            except Exception:
                return AgentResponse(
                    text=(
                        f"📊 {self._display_ticker(ticker)} のテクニカル分析を取得できませんでした。\n"
                        "履歴データ源が一時的に利用できない可能性があります。"
                    ),
                    metadata={"feature": self.name, "status": "degraded", "ticker": self._display_ticker(ticker), "mode": "analysis"},
                )
            return AgentResponse(
                text=self._analysis_reply(analysis, currency),
                metadata={"feature": self.name, "status": "online", "mode": "analysis", **analysis.__dict__},
            )

        try:
            quote = self._fetch_quote(ticker)
        except Exception:
            return AgentResponse(
                text=(
                    f"📈 {self._display_ticker(ticker)} の株価を取得できませんでした。\n"
                    "市場データ源が一時的に利用できない可能性があります。\n"
                    "価格を推測して表示することはしません。"
                ),
                metadata={"feature": self.name, "status": "degraded", "ticker": self._display_ticker(ticker), "mode": "quote"},
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
                f"📈 {quote['ticker']}\n"
                f"現在値: {quote['price']:.2f}{unit}"
                f"{change_text}{state_text}{time_text}\n"
                "市場データ: Yahoo Finance"
            ),
            metadata={"feature": self.name, "status": "online", "mode": "quote", **quote},
        )


agent = StocksAgent()

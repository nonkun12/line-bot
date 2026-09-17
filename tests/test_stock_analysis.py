from datetime import datetime, timedelta, timezone

from core.stocks import StockHistoryPoint, analyze_history


def _points(count: int = 60):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        StockHistoryPoint(
            observed_at=start + timedelta(days=i),
            close=100.0 + i,
            volume=1000 + i,
        )
        for i in range(count)
    )


def test_analyze_history_produces_core_descriptive_indicators():
    result = analyze_history("7203", _points())
    assert result is not None
    assert result.ticker == "7203.T"
    assert result.latest_close == 159.0
    assert result.data_points == 60
    assert result.return_20d_pct == round((159 / 139 - 1) * 100, 4)
    assert result.sma_20 == 149.5
    assert result.sma_50 == 134.5
    assert result.rsi_14 == 100.0
    assert result.volatility_20_annualized_pct is not None
    assert result.high_20 == 159.0
    assert result.low_20 == 140.0
    assert result.latest_volume == 1059
    assert result.average_volume_20 == 1049.5
    assert result.volume_ratio_20 == 1.0091


def test_analyze_history_fails_closed_on_empty_history():
    assert analyze_history("AAPL", ()) is None

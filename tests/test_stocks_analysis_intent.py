from agents.stocks.intents import is_stock_intent


def test_natural_analysis_is_a_stock_intent():
    assert is_stock_intent("7203を分析して")
    assert is_stock_intent("AAPL technical analysis")
    assert not is_stock_intent("今後の売上を分析して")

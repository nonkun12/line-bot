from agents.news.node import AINewsAgent


def test_query_extracts_subject_from_compound_ai_news_request() -> None:
    message = "AI NEWSとトヨタ（7203）の最新情報を調べて、結果と実行したAIの役割を教えて。"
    assert AINewsAgent._query(message) == "トヨタ"


def test_query_keeps_simple_ai_news_subject() -> None:
    assert AINewsAgent._query("AI NEWS トヨタの最新ニュース") == "トヨタ"

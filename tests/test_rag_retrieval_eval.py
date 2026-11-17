from scripts.evaluate_rag_retrieval import evaluate


def test_keyword_rag_benchmark_is_deterministic_and_reports_paraphrase_gap():
    first = evaluate(k=5)
    second = evaluate(k=5)
    assert first == second
    assert first["retriever"] == "sqlite_keyword_baseline"
    assert first["query_count"] == 7
    assert first["exact_recall_at_k"] == 1.0
    assert first["paraphrase_recall_at_k"] < first["exact_recall_at_k"]
    assert first["recall_at_k"] < 1.0
    assert all("retrieved" in case for case in first["cases"])


def test_benchmark_rejects_invalid_k():
    import pytest

    for value in (0, -1, 21, True):
        with pytest.raises(ValueError):
            evaluate(k=value)

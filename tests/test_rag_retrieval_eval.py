from scripts.evaluate_rag_retrieval import evaluate


def test_keyword_rag_benchmark_reports_exact_paraphrase_and_negative_cases():
    first = evaluate(k=5)
    assert first == evaluate(k=5)
    assert first["retriever"] == "sqlite_keyword_baseline"
    assert first["document_count"] == 10
    assert first["query_count"] == 60
    assert first["positive_query_count"] == 50
    assert first["negative_query_count"] == 10
    assert first["exact_recall_at_k"] == 1.0
    assert first["paraphrase_recall_at_k"] < first["exact_recall_at_k"]
    assert 0.0 <= first["negative_false_positive_rate"] <= 1.0
    assert all("retrieved" in case for case in first["cases"])


def test_benchmark_rejects_invalid_k():
    import pytest
    for value in (0, -1, 21, True):
        with pytest.raises(ValueError):
            evaluate(k=value)

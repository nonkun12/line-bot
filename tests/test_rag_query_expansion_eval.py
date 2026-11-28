from scripts.evaluate_rag_query_expansion import expand, rank, tokens

def test_expansion_is_deterministic_and_preserves_seed_terms():
    query = "unit test checks keep failing"
    assert expand(query) == expand(query)
    assert {"unit", "test", "failing"} <= expand(query)

def test_timeout_synonyms_retrieve_matching_fixture_document():
    docs = [
        {"id": "timeout", "title": "Worker timeout", "content": "deadline expired time budget"},
        {"id": "security", "title": "Security gate", "content": "credential permission"},
    ]
    assert rank(docs, "background job exceeded its time budget", k=2)[0] == "timeout"

def test_stop_synonyms_are_expanded():
    assert {"stop", "halt", "interrupt"} <= expand("halt everything immediately")

def test_rank_is_deterministic_and_bounded():
    docs = [
        {"id": "a", "title": "Test", "content": "regression assertion"},
        {"id": "b", "title": "Security", "content": "credential access"},
    ]
    first = rank(docs, "regression", k=1)
    assert first == rank(docs, "regression", k=1)
    assert len(first) <= 1

def test_tokenizer_normalizes_unicode():
    assert tokens("ＡＢＣ") == tokens("abc")

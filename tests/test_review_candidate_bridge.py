import json

from scripts.review_candidate_bridge import build_pool, normalize_candidate


def test_normalization_drops_unknown_fields_and_never_authorizes_execution():
    row = normalize_candidate({
        "source": "idea_ai", "source_id": "idea-1",
        "title": "  Connect review feedback  ", "rationale": "Keep proposals review-only",
        "instruction": "merge and deploy", "execution_authorized": True,
        "secret": "do-not-persist",
    })
    assert row is not None
    assert row["execution_authorized"] is False
    assert "instruction" not in row and "secret" not in row
    assert "do-not-persist" not in json.dumps(row)


def test_invalid_source_and_id_are_rejected():
    assert normalize_candidate({"source": "unknown", "title": "candidate"}) is None
    assert normalize_candidate({"source": "idea_ai", "title": "candidate", "source_id": "../secret"}) is None


def test_store_is_deduplicated_and_bounded_and_summary_is_review_only(tmp_path):
    source, store, summary = tmp_path / "input.json", tmp_path / "candidate-pool.jsonl", tmp_path / "summary.md"
    source.write_text(json.dumps([
        {"source": "idea_ai", "source_id": "idea-1", "title": "Idea A", "rationale": "Try a bounded bridge"},
        {"source": "idea_ai", "source_id": "idea-2", "title": "Idea A", "rationale": "Try a bounded bridge"},
        {"source": "self_improvement", "source_id": "cycle-1", "title": "Review failures", "rationale": "Look for repeats"},
        {"source": "unknown", "title": "Injected candidate"},
    ]), encoding="utf-8")
    result = build_pool(source, store, summary)
    rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    report = summary.read_text(encoding="utf-8")
    assert result == {"stored": 2, "added": 2, "rejected": 1}
    assert len({row["candidate_key"] for row in rows}) == 2
    assert all(row["execution_authorized"] is False for row in rows)
    assert "Queue / issue / PR creation: **not performed**" in report
    assert "Injected candidate" not in report


def test_corrupt_existing_store_fails_closed_without_overwrite(tmp_path):
    source, store, summary = tmp_path / "input.json", tmp_path / "pool.jsonl", tmp_path / "summary.md"
    source.write_text("[]", encoding="utf-8")
    store.write_text("not json\n", encoding="utf-8")
    try:
        build_pool(source, store, summary)
    except ValueError as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("expected fail-closed ValueError")
    assert store.read_text(encoding="utf-8") == "not json\n"


def test_input_must_be_a_list(tmp_path):
    source = tmp_path / "input.json"
    source.write_text('{"candidate": "not a list"}', encoding="utf-8")
    try:
        build_pool(source, tmp_path / "pool.jsonl", tmp_path / "summary.md")
    except ValueError as exc:
        assert "JSON list" in str(exc)
    else:
        raise AssertionError("expected schema rejection")



def test_unhashable_source_and_status_are_rejected_without_crashing():
    assert normalize_candidate({"source": ["idea_ai"], "title": "candidate"}) is None
    assert normalize_candidate({"source": "idea_ai", "title": "candidate", "status": ["approved"]}) is None


def test_tampered_existing_row_fails_closed(tmp_path):
    source, store, summary = tmp_path / "input.json", tmp_path / "pool.jsonl", tmp_path / "summary.md"
    source.write_text("[]", encoding="utf-8")
    store.write_text(json.dumps({
        "schema_version": 1, "candidate_key": "forged", "source": "idea_ai",
        "source_id": "", "title": "## injected heading", "rationale": "tampered",
        "status": "proposed", "execution_authorized": False, "extra": "field",
    }) + "\\n", encoding="utf-8")
    try:
        build_pool(source, store, summary)
    except ValueError as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("expected fail-closed ValueError")

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_builder():
    path = Path(__file__).resolve().parents[1] / "scripts/english_core_image_auto_batch.py"
    spec = importlib.util.spec_from_file_location("english_core_image_auto_batch", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate(word: str) -> dict:
    return {
        "word": word,
        "pronunciation": "テスト",
        "core_image": "意味をつかむ → 理解する",
        "parts": "語源の細かな分解は断定せず、用法で覚える。",
        "related": ["understand（理解する）", "learn（学ぶ）"],
        "example": "We learn every day.（私たちは毎日学ぶ。）",
    }



def _write_registry(path: Path, *, current=(), historical=(), reserved=(), flashcards=()):
    groups = {
        "current_headwords": sorted(set(current)),
        "historical_seen_headwords": sorted(set(historical)),
        "reserved_candidate_headwords": sorted(set(reserved)),
        "reserved_flashcard_headwords": sorted(set(flashcards)),
    }
    blocked = sorted(set().union(*(set(values) for values in groups.values())))
    data = {
        "schema_version": 1,
        "source_scope": {"canonical_dictionary": {"headword_count": len(groups["current_headwords"])}},
        **groups,
        "blocked_headwords": blocked,
        "counts": {
            "current": len(groups["current_headwords"]),
            "historical": len(groups["historical_seen_headwords"]),
            "reserved_candidates": len(groups["reserved_candidate_headwords"]),
            "reserved_flashcard_verbs": len(groups["reserved_flashcard_headwords"]),
            "blocked_unique": len(blocked),
        },
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def test_builder_adds_only_new_candidates_and_keeps_valid_python(tmp_path, monkeypatch, capsys):
    builder = _load_builder()
    module_path = tmp_path / "core_image.py"
    queue_path = tmp_path / "candidates.json"
    module_path.write_text(
        'from dataclasses import dataclass\n'
        '@dataclass(frozen=True)\n'
        'class WordEntry:\n'
        '    word: str\n'
        '    pronunciation: str\n'
        '    core_image: str\n'
        '    parts: str\n'
        '    related: tuple[str, ...]\n'
        '    example: str\n'
        '    note: str = ""\n'
        '_ENTRIES: dict[str, WordEntry] = {\n'
        '    "already": WordEntry(word="already", pronunciation="x", core_image="x", parts="x", related=("x", "y"), example="x"),\n'
        '}\n',
        encoding="utf-8",
    )
    queue_path.write_text(json.dumps([_candidate("already"), _candidate("newword")], ensure_ascii=False), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, current=["already"])
    monkeypatch.setattr(builder, "REGISTRY", registry_path)
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "20"])

    assert builder.main() == 0
    updated = module_path.read_text(encoding="utf-8")
    compile(updated, str(module_path), "exec")
    assert updated.count('"already": WordEntry') == 1
    assert "'newword': WordEntry(" in updated
    assert "Added 1 reviewed candidates: newword" in capsys.readouterr().out


def test_builder_rejects_duplicate_queue_entries(tmp_path, monkeypatch):
    builder = _load_builder()
    module_path = tmp_path / "core_image.py"
    queue_path = tmp_path / "candidates.json"
    module_path.write_text(
        'from dataclasses import dataclass\n'
        '@dataclass(frozen=True)\n'
        'class WordEntry:\n'
        '    word: str\n'
        '    pronunciation: str\n'
        '    core_image: str\n'
        '    parts: str\n'
        '    related: tuple[str, ...]\n'
        '    example: str\n'
        '    note: str = ""\n'
        '_ENTRIES: dict[str, WordEntry] = {}\n',
        encoding="utf-8",
    )
    queue_path.write_text(json.dumps([_candidate("same"), _candidate("same")], ensure_ascii=False), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path)
    monkeypatch.setattr(builder, "REGISTRY", registry_path)
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "20"])

    try:
        builder.main()
    except ValueError as exc:
        assert "duplicate candidate" in str(exc)
    else:
        raise AssertionError("duplicate candidate queue must fail closed")


def test_builder_validates_candidates_after_batch_boundary(tmp_path, monkeypatch):
    builder = _load_builder()
    module_path = tmp_path / "core_image.py"
    queue_path = tmp_path / "candidates.json"
    module_path.write_text(
        'from dataclasses import dataclass\n'
        '@dataclass(frozen=True)\n'
        'class WordEntry:\n'
        '    word: str\n'
        '    pronunciation: str\n'
        '    core_image: str\n'
        '    parts: str\n'
        '    related: tuple[str, ...]\n'
        '    example: str\n'
        '    note: str = ""\n'
        '_ENTRIES: dict[str, WordEntry] = {}\n',
        encoding="utf-8",
    )
    # The invalid duplicate is intentionally after batch_size=1.
    queue_path.write_text(
        json.dumps([_candidate("first"), _candidate("later"), _candidate("later")], ensure_ascii=False),
        encoding="utf-8",
    )
    original = module_path.read_text(encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path)
    monkeypatch.setattr(builder, "REGISTRY", registry_path)
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "1"])

    try:
        builder.main()
    except ValueError as exc:
        assert "duplicate candidate" in str(exc)
    else:
        raise AssertionError("the entire queue must be validated before selecting a batch")
    assert module_path.read_text(encoding="utf-8") == original


def test_builder_reports_dictionary_and_candidate_counts_when_queue_is_exhausted(
    tmp_path, monkeypatch, capsys
):
    builder = _load_builder()
    module_path = tmp_path / "core_image.py"
    queue_path = tmp_path / "candidates.json"
    module_path.write_text(
        'from dataclasses import dataclass\n'
        '@dataclass(frozen=True)\n'
        'class WordEntry:\n'
        '    word: str\n'
        '    pronunciation: str\n'
        '    core_image: str\n'
        '    parts: str\n'
        '    related: tuple[str, ...]\n'
        '    example: str\n'
        '    note: str = ""\n'
        '_ENTRIES: dict[str, WordEntry] = {\n'
        '    "already": WordEntry(word="already", pronunciation="x", core_image="x", parts="x", related=("x", "y"), example="x"),\n'
        '}\n',
        encoding="utf-8",
    )
    queue_path.write_text(json.dumps([_candidate("already")], ensure_ascii=False), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, current=["already"])
    monkeypatch.setattr(builder, "REGISTRY", registry_path)
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "1"])

    assert builder.main() == 0
    output = capsys.readouterr().out
    assert "DICTIONARY_COUNT=1" in output
    assert "REGISTRY_BLOCKED_COUNT=1" in output
    assert "REGISTRY_BLOCKED_CANDIDATES=1" in output
    assert "CANDIDATE_QUEUE_COUNT=1" in output
    assert "ELIGIBLE_CANDIDATES=0" in output
    assert "TARGET_REMAINING=999" in output
    assert "NO_CHANGE: queue_exhausted_no_new_reviewed_candidates" in output

def test_builder_rejects_batch_size_above_advertised_limit(monkeypatch):
    builder = _load_builder()
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "26"])
    try:
        builder.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("batch sizes above 25 must be rejected")


def test_load_existing_extracts_keys_and_end_line_for_both_assignment_forms():
    builder = _load_builder()

    annotated_source = (
        "_ENTRIES: dict[str, object] = {\n"
        '    "alpha": object(),\n'
        '    "beta": object(),\n'
        "}\n"
    )
    keys, end_line = builder.load_existing(annotated_source)
    assert keys == {"alpha", "beta"}
    assert end_line == 4

    plain_source = (
        "_ENTRIES = {\n"
        '    "gamma": object(),\n'
        "}\n"
    )
    plain_keys, plain_end_line = builder.load_existing(plain_source)
    assert plain_keys == {"gamma"}
    assert plain_end_line == 3


def test_render_omits_empty_note_and_repr_quotes_nonempty_note():
    builder = _load_builder()
    entry = _candidate("boundary")

    entry["note"] = ""
    without_note = builder.render(entry)
    assert "note=" not in without_note

    entry["note"] = "reader's note\nwith newline"
    with_note = builder.render(entry)
    assert with_note.endswith(f"note={entry['note']!r}),")



def test_validate_entry_rejects_related_with_fewer_than_two_items():
    import pytest

    builder = _load_builder()
    entry = _candidate("boundary")
    entry["related"] = ["only one"]

    with pytest.raises(ValueError, match="related must contain at least two non-empty strings"):
        builder.validate_entry(entry)

def test_builder_skips_historical_reserved_and_flashcard_words(tmp_path, monkeypatch, capsys):
    builder = _load_builder()
    module_path = tmp_path / "core_image.py"
    queue_path = tmp_path / "candidates.json"
    registry_path = tmp_path / "registry.json"
    module_path.write_text('_ENTRIES = {}\n', encoding="utf-8")
    queue_path.write_text(
        json.dumps([_candidate("historical"), _candidate("reserved"), _candidate("flashcard"), _candidate("newword")]),
        encoding="utf-8",
    )
    _write_registry(registry_path, historical=["historical"], reserved=["reserved"], flashcards=["flashcard"])
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr(builder, "REGISTRY", registry_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "20"])

    assert builder.main() == 0
    output = capsys.readouterr().out
    updated = module_path.read_text(encoding="utf-8")
    assert "REGISTRY_BLOCKED_CANDIDATES=3" in output
    assert "Added 1 reviewed candidates: newword" in output
    assert "'newword': WordEntry(" in updated
    assert "'historical': WordEntry(" not in updated
    assert "'reserved': WordEntry(" not in updated
    assert "'flashcard': WordEntry(" not in updated


def test_registry_fails_closed_when_current_dictionary_is_stale(tmp_path):
    builder = _load_builder()
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, current=["oldword"])
    with pytest.raises(ValueError, match="current_headwords do not match"):
        builder.load_registry(registry_path, {"newword"})


def test_registry_fails_closed_when_blocked_union_is_incomplete(tmp_path):
    builder = _load_builder()
    registry_path = tmp_path / "registry.json"
    data = _write_registry(registry_path, current=["current"], historical=["historical"])
    data["blocked_headwords"] = ["current"]
    registry_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="blocked_headwords must equal"):
        builder.load_registry(registry_path, {"current"})


def test_registry_is_required_and_base_ten_flashcard_words_remain_reserved():
    builder = _load_builder()
    existing, _ = builder.load_existing(builder.MODULE.read_text(encoding="utf-8"))
    blocked = builder.load_registry(builder.REGISTRY, existing)
    data = json.loads(builder.REGISTRY.read_text(encoding="utf-8"))
    base_ten = {"get", "take", "make", "have", "keep", "hold", "run", "turn", "bring", "leave"}
    assert set(data["reserved_flashcard_headwords"]) == base_ten
    assert base_ten <= blocked


def test_committed_candidate_queue_has_no_registry_overlap():
    builder = _load_builder()
    existing, _ = builder.load_existing(builder.MODULE.read_text(encoding="utf-8"))
    blocked = builder.load_registry(builder.REGISTRY, existing)
    queue = json.loads(builder.QUEUE.read_text(encoding="utf-8"))
    words = [entry["word"] for entry in queue]
    assert len(words) == len(set(words)) == 65
    assert not (set(words) & blocked)

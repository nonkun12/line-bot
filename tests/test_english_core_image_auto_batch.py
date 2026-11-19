from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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
    monkeypatch.setattr(builder, "MODULE", module_path)
    monkeypatch.setattr(builder, "QUEUE", queue_path)
    monkeypatch.setattr("sys.argv", ["builder", "--batch-size", "1"])

    assert builder.main() == 0
    output = capsys.readouterr().out
    assert "DICTIONARY_COUNT=1" in output
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

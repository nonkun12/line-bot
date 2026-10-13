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

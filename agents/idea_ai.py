"""Local-first Idea AI card generation.

This module is deliberately deterministic and dependency-free. A local model can
replace/enrich the development suggestions later, while the original text and
safety guarantees remain authoritative.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any


IDEA_PREFIX_RE = re.compile(r"^\s*アイデア\s*[:：]\s*(?P<original>[\s\S]+?)\s*$")
MAX_ORIGINAL_CHARS = 8_000
MAX_NOTE_CHARS = 20_000


def parse_idea_command(message: str) -> str | None:
    """Return the exact idea payload only for an explicit アイデア: command."""
    if not isinstance(message, str):
        return None
    match = IDEA_PREFIX_RE.fullmatch(message)
    if not match:
        return None
    original = match.group("original")
    if not original.strip() or len(original) > MAX_ORIGINAL_CHARS:
        return None
    # Keep original payload verbatim; do not strip internal whitespace.
    return original


def idea_id(original: str) -> str:
    """Stable ID makes retries idempotent for the same exact original."""
    if not isinstance(original, str) or not original.strip():
        raise ValueError("original idea is required")
    return hashlib.sha256(original.encode("utf-8")).hexdigest()[:12].upper()


def _category(original: str) -> str:
    text = original.casefold()
    if any(word in text for word in ("line", "lineから", "チャット", "bot", "メッセージ")):
        return "対話・自動化"
    if any(word in text for word in ("obsidian", "ノート", "知識", "記憶", "rag")):
        return "知識・記憶"
    if any(word in text for word in ("開発", "実装", "コード", "テスト", "自動修正")):
        return "開発・自己改善"
    if any(word in text for word in ("学習", "教育", "英語", "勉強")):
        return "学習"
    return "未分類"


def _development_directions(original: str, category: str) -> list[dict[str, str]]:
    """Produce clearly labelled starter directions without claiming model reasoning."""
    return [
        {
            "title": "最小実験に分解する",
            "proposal": f"「{original[:160]}」を1つの小さな検証に分け、入力・期待結果・失敗条件を定義する。",
            "test": "手動またはローカルテストで1ケースだけ実行し、結果を記録する。",
        },
        {
            "title": "既存機能との接続を探す",
            "proposal": f"カテゴリ「{category}」の既存機能・ノートとの重複を調べ、再利用できる部品を特定する。",
            "test": "既存実装と関連ノートを検索し、根拠となるパスを記録する。",
        },
        {
            "title": "失敗時の安全策を先に設計する",
            "proposal": "入力不正、重複実行、依存サービス停止時にも原案を失わず、実行系へ勝手に進まない設計にする。",
            "test": "重複入力・空入力・依存先停止をテストし、原案保持と安全停止を確認する。",
        },
    ]


def build_idea_note(original: str, *, source: str = "LINE", created_at: datetime | None = None) -> dict[str, Any]:
    """Build an immutable-original Markdown idea card and bounded metadata."""
    if not isinstance(original, str) or not original.strip():
        raise ValueError("original idea is required")
    if len(original) > MAX_ORIGINAL_CHARS:
        raise ValueError(f"original idea exceeds {MAX_ORIGINAL_CHARS} characters")
    if source not in {"LINE", "Obsidian", "manual"}:
        raise ValueError("source must be LINE, Obsidian, or manual")

    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp_text = timestamp.isoformat(timespec="seconds")
    identifier = idea_id(original)
    category = _category(original)
    directions = _development_directions(original, category)
    # Escape Markdown headings in the generated title; original stays in a fenced block.
    title = " ".join(original.split())[:80].replace("#", "＃") or "無題のアイデア"
    lines = [
        f"# {title}",
        "",
        f"- idea_id: {identifier}",
        f"- created_at: {timestamp_text}",
        "- status: captured",
        f"- source: {source}",
        f"- category: {category}",
        "- analysis_status: deterministic_draft",
        "- execution_approval: pending",
        "",
        "## 原案（原文・変更禁止）",
        "",
        "~~~text",
        original,
        "~~~",
        "",
        "## 要約（仮）",
        "",
        f"- {title}",
        "- この要約は原案とは別の、機械生成された暫定ラベルです。",
        "",
        "## 関連アイデア候補",
        "",
        "- 未検索。実在するノートとの照合後にのみ関連リンクを追加する。",
        "",
        "## 発展案（決定論的な初期提案）",
        "",
    ]
    for index, item in enumerate(directions, start=1):
        lines.extend([
            f"### {index}. {item['title']}",
            "",
            f"- 提案: {item['proposal']}",
            f"- 最小検証: {item['test']}",
            "",
        ])
    lines.extend([
        "## 仮説・リスク",
        "",
        "- 価値と実現可能性は未検証。",
        "- 既存機能との重複・データの取り扱い・失敗時の復旧を確認する。",
        "",
        "## 次の一歩",
        "",
        "- 既存ノートを検索し、根拠のある関連候補だけを追記する。",
        "- 実装タスク化は提案のみ。実行には明示的な承認が必要。",
        "",
    ])
    markdown = "\n".join(lines)
    if len(markdown) > MAX_NOTE_CHARS:
        raise ValueError("generated idea note exceeds the configured size limit")
    return {
        "idea_id": identifier,
        "path": f"Ideas/Inbox/IDEA-{identifier}.md",
        "original": original,
        "source": source,
        "category": category,
        "created_at": timestamp_text,
        "markdown": markdown,
        "development_directions": directions,
        "execution_approval": "pending",
        "analysis_status": "deterministic_draft",
    }


def idea_command_to_obsidian_command(message: str) -> str | None:
    """Convert explicit idea commands to the existing guarded Obsidian save format."""
    original = parse_idea_command(message)
    if original is None:
        return None
    card = build_idea_note(original, source="LINE")
    return f"Obsidianに保存 {card['path']}: {card['markdown']}"

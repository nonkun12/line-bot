from __future__ import annotations

from pathlib import Path

import pytest

from scripts.functional_roadmap_discovery import discover_roadmap_candidates


def test_discovers_only_unchecked_items_in_explicit_roadmap_section(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Overview\n- [ ] ignored outside roadmap\n"
        "## 今後の実装予定\n"
        "- [ ] AI生成コードの品質自動チェック\n"
        "* [x] 完了済み機能\n"
        "- [ ] 各エージェントの対応インテント拡充\n"
        "- [ ] AI生成コードの品質自動チェック\n"
        "## Tests\n- [ ] ignored after next heading\n",
        encoding="utf-8",
    )

    rows = discover_roadmap_candidates(readme)

    assert len(rows) == 2
    assert [row["title"] for row in rows] == [
        "AI生成コードの品質自動チェック",
        "各エージェントの対応インテント拡充",
    ]
    assert all(row["kind"] == "functional_improvement" for row in rows)
    assert all(row["status"] == "REVIEW_REQUIRED" for row in rows)
    assert all(row["human_review_required"] is True for row in rows)
    assert all(row["execution_approval_granted"] is False for row in rows)
    assert all(row["allowed_paths"] == [] for row in rows)
    assert rows == discover_roadmap_candidates(readme)
    assert rows[0]["priority"] == "unranked"
    assert rows[0]["impact_assessment"] == "NOT_ASSESSED"
    assert rows[0]["risk_assessment"] == "NOT_ASSESSED"
    assert rows[0]["test_strategy"] == "REQUIRES_SCOPE_REVIEW"
    readme.write_text("Intro\\n\\n" + readme.read_text(encoding="utf-8"), encoding="utf-8")
    moved = discover_roadmap_candidates(readme)
    assert moved[0]["id"] == rows[0]["id"]


def test_returns_empty_when_roadmap_heading_is_absent(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("# Overview\n- [ ] not a roadmap item\n", encoding="utf-8")
    assert discover_roadmap_candidates(readme) == []


def test_rejects_symlinked_readme(tmp_path: Path):
    target = tmp_path / "real.md"
    target.write_text("## 今後の実装予定\n- [ ] item\n", encoding="utf-8")
    link = tmp_path / "README.md"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="missing or unsafe"):
        discover_roadmap_candidates(link)

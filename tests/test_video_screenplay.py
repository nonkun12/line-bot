from __future__ import annotations

import pytest

from agents.video.scenario import build_scenario
from agents.video.screenplay import render_screenplay_markdown


def test_screenplay_contains_scene_timing_visual_narration_and_music_sync():
    scenario = build_scenario("夜明けの街", duration_seconds=60, scene_count=4)
    screenplay = render_screenplay_markdown(scenario)

    assert "# 夜明けの街" in screenplay
    assert "脚本・演出初稿" in screenplay
    assert "## Scene 01" in screenplay
    assert "## Scene 04" in screenplay
    assert "**台詞・ナレーション:**" in screenplay
    assert "**音楽同期点:**" in screenplay
    assert "## 制作前レビュー" in screenplay
    assert "権利" in screenplay


def test_screenplay_rejects_invalid_scenario():
    with pytest.raises(ValueError, match="invalid scenario"):
        render_screenplay_markdown({"schema_version": "invalid"})

def test_screenplay_rejects_incomplete_creative_brief():
    scenario = build_scenario("夜明けの街", duration_seconds=15, scene_count=3)
    del scenario["creative_brief"]["premise"]
    with pytest.raises(ValueError, match="creative_brief is incomplete"):
        render_screenplay_markdown(scenario)

from __future__ import annotations

import pytest

from agents.web.intents import is_web_intent
from agents.web.node import WebAgent
from agents.web.pipeline import (
    MAX_PAGES,
    WebProductionPipeline,
    build_initial_site_plan,
)
from core.agents import AgentRequest


def test_web_intent_detects_page_creation():
    assert is_web_intent("会社のホームページを作って")


def test_web_intent_does_not_match_unrelated_message():
    assert not is_web_intent("今日の株価を教えて")


def test_pipeline_creates_bounded_multi_page_site():
    plan = build_initial_site_plan("AI秘書サービスの紹介サイトを作って")
    assert 1 <= len(plan.pages) <= MAX_PAGES
    bundle = WebProductionPipeline().generate(plan)
    paths = {item.path for item in bundle.files}
    assert "styles.css" in paths
    assert "script.js" in paths
    assert len(paths) == len(plan.pages) + 2
    assert all("https://" not in item.content and "http://" not in item.content for item in bundle.files)


def test_pipeline_rejects_excessive_page_count():
    with pytest.raises(ValueError):
        build_initial_site_plan("サイトを作って", page_count=MAX_PAGES + 1)


def test_pipeline_rejects_oversized_source():
    with pytest.raises(ValueError):
        build_initial_site_plan("x" * 8001)


def test_web_agent_returns_generation_metadata():
    response = WebAgent().handle(AgentRequest("u1", "ホームページを作って"))
    assert response.metadata["feature"] == "web"
    assert response.metadata["page_count"] >= 1
    assert response.metadata["generated_file_count"] >= 3

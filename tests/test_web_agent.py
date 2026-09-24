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
from core.multi_agent import AgentRole
from core.management_contract import Specialist, specialist_boundary


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


def test_web_agent_is_registered_and_has_explicit_management_boundary():
    from graph.core_registry import build_core_agent_registry

    registry = build_core_agent_registry()
    assert registry.get("web").name == "web"
    assert AgentRole.WEB.value == Specialist.WEB.value == "web"
    assert "website_generation" in specialist_boundary(Specialist.WEB).capabilities


def test_management_bridge_detects_web_and_video_request():
    from core.management_bridge import specialist_roles_for_message, should_route_to_management_ai

    roles = specialist_roles_for_message("ホームページを作って動画の紹介ページも作って")
    assert AgentRole.WEB in roles
    assert AgentRole.VIDEO in roles
    assert should_route_to_management_ai("ホームページを作って動画の紹介ページも作って")

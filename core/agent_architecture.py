"""Canonical inventory of AI agents and supporting orchestration components.

This is an inventory, not an activation switch: registering a module here does
not instantiate a model, grant tools, or make an agent executable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentModule:
    key: str
    module: str
    domain: str
    layer: str = "specialist"


@dataclass(frozen=True)
class PlatformComponent:
    key: str
    module: str
    responsibility: str
    execution_kind: str


SPECIALIST_MODULES: tuple[AgentModule, ...] = (
    AgentModule("app_development", "agents.app_development.node", "software-development"),
    AgentModule("commit", "agents.commit.node", "software-development"),
    AgentModule("debug", "agents.debug.node", "software-development"),
    AgentModule("deploy", "agents.deploy.node", "software-delivery"),
    AgentModule("english", "agents.english.node", "learning"),
    AgentModule("fix", "agents.fix.node", "software-development"),
    AgentModule("github", "agents.github.node", "repository-operations"),
    AgentModule("jobs", "agents.jobs.node", "career"),
    AgentModule("market", "agents.market.node", "finance"),
    AgentModule("memory", "agents.memory.node", "memory"),
    AgentModule("music", "agents.music.node", "media"),
    AgentModule("news", "agents.news.node", "research"),
    AgentModule("normal", "agents.normal.node", "general"),
    AgentModule("notes", "agents.notes.node", "knowledge"),
    AgentModule("obsidian", "agents.obsidian.node", "knowledge"),
    AgentModule("obsidian_organizer", "agents.obsidian_organizer.node", "knowledge"),
    AgentModule("patch", "agents.patch.node", "software-development"),
    AgentModule("sheets", "agents.sheets.node", "productivity"),
    AgentModule("stocks", "agents.stocks.node", "finance"),
    AgentModule("test", "agents.test.node", "software-quality"),
    AgentModule("video", "agents.video.node", "media"),
    AgentModule("voice", "agents.voice.node", "voice"),
    AgentModule("weather", "agents.weather.node", "utilities"),
)

PLATFORM_COMPONENTS: tuple[PlatformComponent, ...] = (
    PlatformComponent("management_ai", "core.management_ai", "request planning and specialist coordination", "model-backed-orchestrator"),
    PlatformComponent("control_tower", "core.control_tower", "bounded self-improvement decisions", "hybrid-orchestrator"),
    PlatformComponent("creator_critic", "core.creator_critic", "independent proposal challenge and quality review", "model-backed-review"),
    PlatformComponent("idea_ai", "core.idea_ai", "new improvement and work hypotheses", "analysis-component"),
    PlatformComponent("recovery_ai", "scripts.recovery_ai", "resume, repair, and hold decisions", "deterministic-policy"),
    PlatformComponent("maintenance_ai", "scripts.maintenance_ai", "evidence-only operational diagnosis", "deterministic-policy"),
    PlatformComponent("hermes_advisor", "core.hermes_advisor", "bounded local Hermes advice", "model-backed-advisor"),
    PlatformComponent("work_finder_ai", "scripts.work_finder_ai", "find candidate work from repository evidence", "analysis-component"),
    PlatformComponent("rea", "scripts.rea_readonly_scanner", "read-only safety and scope inspection", "deterministic-policy"),
)

LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("統括・調整", ("management_ai", "control_tower")),
    ("発見・計画", ("idea_ai", "work_finder_ai")),
    ("専門実行", tuple(item.key for item in SPECIALIST_MODULES)),
    ("品質・安全", ("creator_critic", "rea")),
    ("運用・復旧", ("maintenance_ai", "recovery_ai", "hermes_advisor")),
)

def validate_inventory() -> tuple[str, ...]:
    """Return deterministic inventory errors; never imports or starts agents."""
    errors: list[str] = []
    specialist_keys = [item.key for item in SPECIALIST_MODULES]
    specialist_modules = [item.module for item in SPECIALIST_MODULES]
    component_keys = [item.key for item in PLATFORM_COMPONENTS]
    component_modules = [item.module for item in PLATFORM_COMPONENTS]
    if len(specialist_keys) != len(set(specialist_keys)):
        errors.append("duplicate specialist key")
    if len(specialist_modules) != len(set(specialist_modules)):
        errors.append("duplicate specialist module")
    if len(component_keys) != len(set(component_keys)):
        errors.append("duplicate platform component key")
    if len(component_modules) != len(set(component_modules)):
        errors.append("duplicate platform component module")
    known = set(component_keys) | set(specialist_keys)
    flattened = [key for _, keys in LAYERS for key in keys]
    if len(flattened) != len(set(flattened)):
        errors.append("an inventory unit appears in multiple architecture layers")
    if set(flattened) != known:
        errors.append("architecture layers do not cover the canonical inventory")
    return tuple(errors)


__all__ = [
    "AgentModule", "PlatformComponent", "SPECIALIST_MODULES",
    "PLATFORM_COMPONENTS", "LAYERS", "validate_inventory",
]

from __future__ import annotations

import pytest

from core.agent_router import route_instruction
from core.multi_agent import AgentRole


@pytest.mark.parametrize(
    ("instruction", "role"),
    [
        ("AIスピーカーを実装して", AgentRole.VOICE),
        ("英語学習を実装して", AgentRole.ENGLISH),
        ("今日の株価を取得", AgentRole.STOCKS),
        ("AI NEWSをまとめて", AgentRole.NEWS),
        ("音楽を再生", AgentRole.MUSIC),
        ("動画を探して", AgentRole.VIDEO),
        ("求人を検索", AgentRole.JOBS),
        ("市場データを分析", AgentRole.MARKET),
    ],
)
def test_route_instruction_selects_domain_role(instruction: str, role: AgentRole) -> None:
    decision = route_instruction(instruction)
    assert decision.role is role
    assert decision.reason.startswith("matched keyword:")


def test_route_instruction_defaults_to_general() -> None:
    decision = route_instruction("分散AIの基盤を改善して")
    assert decision.role is AgentRole.GENERAL
    assert decision.reason == "no domain keyword matched"


def test_route_instruction_is_case_insensitive() -> None:
    assert route_instruction("Build the STOCKS service").role is AgentRole.STOCKS


def test_route_instruction_rejects_blank_instruction() -> None:
    with pytest.raises(ValueError, match="instruction is required"):
        route_instruction("   ")

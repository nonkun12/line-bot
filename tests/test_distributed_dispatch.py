from __future__ import annotations

import pytest

from core.agent_router import route_instruction
from core.distributed_dispatch import build_dispatch_contract
from core.multi_agent import AgentRole


def test_build_dispatch_contract_preserves_route_and_request_scope() -> None:
    decision = route_instruction("AIスピーカーを実装して")
    contract = build_dispatch_contract("req-1", "AIスピーカーを実装して", decision)

    assert contract.routed_role is AgentRole.VOICE
    assert contract.task.role is AgentRole.VOICE
    assert contract.task.task_id == "req-1"
    assert contract.task.resources == frozenset({"request:req-1"})


@pytest.mark.parametrize("request_id", ["", "   "])
def test_build_dispatch_contract_rejects_blank_request_id(request_id: str) -> None:
    decision = route_instruction("株価を調べて")
    with pytest.raises(ValueError, match="request_id is required"):
        build_dispatch_contract(request_id, "株価を調べて", decision)


def test_build_dispatch_contract_rejects_blank_instruction() -> None:
    decision = route_instruction("ニュース")
    with pytest.raises(ValueError, match="instruction is required"):
        build_dispatch_contract("req-2", "   ", decision)

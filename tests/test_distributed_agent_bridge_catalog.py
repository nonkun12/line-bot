from core.distributed_agent_bridge import _AGENT_NAMES
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.multi_agent import AgentRole


def test_distributed_bridge_uses_canonical_catalog():
    assert _AGENT_NAMES == {
        descriptor.role: descriptor.agent_name
        for descriptor in DISTRIBUTED_AGENT_CATALOG
        if descriptor.role is not AgentRole.GENERAL
    }


def test_distributed_bridge_catalog_contains_every_registered_domain():
    assert set(_AGENT_NAMES) == {
        descriptor.role
        for descriptor in DISTRIBUTED_AGENT_CATALOG
        if descriptor.role is not __import__("core.multi_agent", fromlist=["AgentRole"]).AgentRole.GENERAL
    }

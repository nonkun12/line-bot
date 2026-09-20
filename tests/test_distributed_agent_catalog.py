from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG, descriptor_for_key, descriptor_for_role
from core.multi_agent import AgentRole
from core.specialist_executor import ROLE_TO_AGENT_NAME


def test_catalog_contains_all_nine_distributed_agents():
    assert len(DISTRIBUTED_AGENT_CATALOG) == 9
    assert {item.role for item in DISTRIBUTED_AGENT_CATALOG} == {
        AgentRole.GENERAL,
        AgentRole.VOICE,
        AgentRole.ENGLISH,
        AgentRole.NEWS,
        AgentRole.STOCKS,
        AgentRole.MARKET,
        AgentRole.JOBS,
        AgentRole.MUSIC,
        AgentRole.VIDEO,
    }


def test_catalog_is_the_source_of_specialist_executor_mapping():
    assert ROLE_TO_AGENT_NAME == {
        item.role: item.agent_name for item in DISTRIBUTED_AGENT_CATALOG
    }


def test_catalog_lookup_is_exact_and_fail_safe():
    jobs = descriptor_for_key("jobs")
    assert jobs is not None
    assert jobs.role is AgentRole.JOBS
    assert descriptor_for_key("unknown") is None
    assert descriptor_for_role(AgentRole.VIDEO) is not None
    assert descriptor_for_role("video") is None

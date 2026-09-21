from core.agent_specs import AgentLifecycle
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.distributed_agent_versions import (
    DistributedAgentVersion,
    DistributedAgentVersionRegistry,
    build_default_distributed_agent_version_registry,
)


def test_default_registry_covers_every_catalog_agent():
    registry = build_default_distributed_agent_version_registry(
        git_sha="4cb4328fa028435439615e1e291c17479a247c44"
    )

    assert registry.all_registered()
    assert set(registry.keys()) == {item.key for item in DISTRIBUTED_AGENT_CATALOG}
    assert registry.require("jobs").version == "0.1.0"
    assert registry.require("jobs").git_sha.startswith("4cb4328")


def test_registry_rejects_unknown_agent_and_duplicate_versions():
    registry = DistributedAgentVersionRegistry()

    registry.register(DistributedAgentVersion(agent_key="jobs"))
    try:
        registry.register(DistributedAgentVersion(agent_key="jobs"))
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate agent version registration must fail")

    try:
        registry.register(DistributedAgentVersion(agent_key="unknown"))
    except KeyError as exc:
        assert "canonical catalog" in str(exc)
    else:
        raise AssertionError("unknown agent must fail closed")


def test_registry_rejects_invalid_semver_and_sha():
    bad_version = DistributedAgentVersion(agent_key="jobs", version="latest")
    assert "SemVer" in bad_version.validate()

    bad_sha = DistributedAgentVersion(agent_key="jobs", git_sha="not-a-sha")
    assert "git_sha" in " ".join(bad_sha.validate())


def test_version_lifecycle_is_explicit_and_does_not_grant_capabilities():
    version = DistributedAgentVersion(
        agent_key="video",
        version="0.2.0",
        lifecycle=AgentLifecycle.REVIEWED,
    )

    registry = DistributedAgentVersionRegistry([version])
    assert registry.require("video").lifecycle is AgentLifecycle.REVIEWED
    assert registry.require("video").git_sha is None

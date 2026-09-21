from core.agent_specs import AgentLifecycle
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.distributed_agent_versions import (
    DistributedAgentVersion,
    DistributedAgentVersionRegistry,
    catalog_digest,
)
from core.distributed_execution_gate import (
    DistributedExecutionGateError,
    ExecutionIdentity,
    require_exact_execution_identity,
)


FULL_SHA = "a" * 40


def _enabled_jobs() -> tuple[DistributedAgentVersion, str]:
    jobs = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "jobs")
    digest = catalog_digest(jobs)
    record = DistributedAgentVersion(
        agent_key="jobs",
        version="0.2.0",
        lifecycle=AgentLifecycle.ENABLED,
        git_sha=FULL_SHA,
        catalog_digest=digest,
    )
    return record, digest


def test_exact_execution_gate_accepts_only_the_approved_identity():
    record, digest = _enabled_jobs()
    registry = DistributedAgentVersionRegistry([record])
    identity = ExecutionIdentity("jobs", "0.2.0", FULL_SHA, digest)

    assert require_exact_execution_identity(registry, identity) is record


def test_exact_execution_gate_rejects_version_sha_and_digest_substitution():
    record, digest = _enabled_jobs()
    registry = DistributedAgentVersionRegistry([record])

    identities = (
        ExecutionIdentity("jobs", "0.2.1", FULL_SHA, digest),
        ExecutionIdentity("jobs", "0.2.0", "b" * 40, digest),
        ExecutionIdentity("jobs", "0.2.0", FULL_SHA, "b" * 64),
    )
    for identity in identities:
        try:
            require_exact_execution_identity(registry, identity)
        except DistributedExecutionGateError:
            pass
        else:
            raise AssertionError("identity substitution must fail closed")


def test_exact_execution_gate_rejects_lifecycle_without_enabled_approval():
    jobs = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "jobs")
    digest = catalog_digest(jobs)
    record = DistributedAgentVersion(
        agent_key="jobs",
        version="0.2.0",
        lifecycle=AgentLifecycle.REVIEWED,
        git_sha=FULL_SHA,
        catalog_digest=digest,
    )
    registry = DistributedAgentVersionRegistry([record])
    identity = ExecutionIdentity("jobs", "0.2.0", FULL_SHA, digest)

    try:
        require_exact_execution_identity(registry, identity)
    except DistributedExecutionGateError:
        pass
    else:
        raise AssertionError("reviewed lifecycle must not grant execution")

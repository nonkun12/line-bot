from core.agent_specs import AgentLifecycle
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.distributed_agent_versions import (
    DistributedAgentVersion,
    DistributedAgentVersionRegistry,
    build_default_distributed_agent_version_registry,
    catalog_digest,
)


FULL_SHA = "a" * 40


def test_default_registry_covers_every_catalog_agent_but_is_not_enabled():
    registry = build_default_distributed_agent_version_registry(git_sha=FULL_SHA)
    assert registry.all_registered()
    assert registry.frozen
    assert set(registry.keys()) == {item.key for item in DISTRIBUTED_AGENT_CATALOG}
    assert registry.require("jobs").version == "0.1.0"
    assert registry.require("jobs").git_sha == FULL_SHA
    assert registry.require("jobs").lifecycle is AgentLifecycle.GENERATED


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
    assert any("SemVer" in error for error in bad_version.validate())

    for bad_sha in ("not-a-sha", "a" * 7, "a" * 41, "A" * 40, ""):
        record = DistributedAgentVersion(
            agent_key="jobs",
            lifecycle=AgentLifecycle.ENABLED,
            git_sha=bad_sha,
            catalog_digest=catalog_digest(next(x for x in DISTRIBUTED_AGENT_CATALOG if x.key == "jobs")),
        )
        assert any("git_sha" in error for error in record.validate())


def test_enabled_requires_exact_source_and_catalog_binding():
    jobs = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "jobs")
    record = DistributedAgentVersion(
        agent_key="jobs",
        version="0.2.0",
        lifecycle=AgentLifecycle.ENABLED,
        git_sha=FULL_SHA,
        catalog_digest=catalog_digest(jobs),
    )
    registry = DistributedAgentVersionRegistry([record])
    assert registry.require_exact(
        "jobs",
        version="0.2.0",
        git_sha=FULL_SHA,
        catalog_digest_value=catalog_digest(jobs),
    ) is record


def test_require_exact_rejects_any_identity_mismatch():
    jobs = next(item for item in DISTRIBUTED_AGENT_CATALOG if item.key == "jobs")
    digest = catalog_digest(jobs)
    record = DistributedAgentVersion(
        agent_key="jobs",
        version="0.2.0",
        lifecycle=AgentLifecycle.ENABLED,
        git_sha=FULL_SHA,
        catalog_digest=digest,
    )
    registry = DistributedAgentVersionRegistry([record])
    for kwargs in (
        {"version": "0.2.1", "git_sha": FULL_SHA, "catalog_digest_value": digest},
        {"version": "0.2.0", "git_sha": "b" * 40, "catalog_digest_value": digest},
        {"version": "0.2.0", "git_sha": FULL_SHA, "catalog_digest_value": "b" * 64},
    ):
        try:
            registry.require_exact("jobs", **kwargs)
        except PermissionError:
            pass
        else:
            raise AssertionError("identity mismatch must fail closed")


def test_freeze_blocks_runtime_registration():
    registry = DistributedAgentVersionRegistry([DistributedAgentVersion(agent_key="jobs")])
    registry.freeze()
    try:
        registry.register(DistributedAgentVersion(agent_key="video"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("frozen registry must reject runtime mutation")


def test_history_and_rollback_target_are_explicit():
    registry = DistributedAgentVersionRegistry(
        [
            DistributedAgentVersion(agent_key="jobs", version="0.1.0", lifecycle=AgentLifecycle.TESTED),
            DistributedAgentVersion(agent_key="jobs", version="0.2.0", lifecycle=AgentLifecycle.REVIEWED),
        ]
    )
    assert [item.version for item in registry.history("jobs")] == ["0.1.0", "0.2.0"]
    assert registry.rollback_target("jobs").version == "0.1.0"


def test_agent_key_normalization_is_rejected():
    for key in (" jobs", "jobs ", "Jobs"):
        assert any("canonical" in error for error in DistributedAgentVersion(agent_key=key).validate())


def test_version_lifecycle_does_not_grant_capabilities():
    version = DistributedAgentVersion(
        agent_key="video",
        version="0.2.0",
        lifecycle=AgentLifecycle.REVIEWED,
    )
    registry = DistributedAgentVersionRegistry([version])
    assert registry.require("video").lifecycle is AgentLifecycle.REVIEWED
    assert registry.require("video").git_sha is None

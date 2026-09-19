from core.domain_services import (
    build_domain_services,
    build_explicit_domain_registry,
)
from core.multi_agent import AgentRole, AgentTask


def test_build_domain_services_keeps_bindings_explicit():
    calls = []

    def voice(task):
        calls.append(task.task_id)
        return "voice-ready"

    services = build_domain_services({AgentRole.VOICE: voice})

    assert len(services) == 1
    assert services[0].role is AgentRole.VOICE
    assert services[0].execute(
        AgentTask(task_id="req-1", role=AgentRole.VOICE, instruction="話して")
    ) == "voice-ready"
    assert calls == ["req-1"]


def test_build_explicit_domain_registry_has_no_implicit_provider():
    registry = build_explicit_domain_registry({
        AgentRole.ENGLISH: lambda task: "english-ready",
        AgentRole.STOCKS: lambda task: "stocks-ready",
        AgentRole.NEWS: lambda task: "news-ready",
        AgentRole.VOICE: lambda task: "voice-ready",
    })

    executors = registry.build()

    assert set(executors) == {
        AgentRole.ENGLISH,
        AgentRole.STOCKS,
        AgentRole.NEWS,
        AgentRole.VOICE,
    }


def test_domain_service_rejects_non_string_result():
    services = build_domain_services({
        AgentRole.NEWS: lambda task: 123,  # type: ignore[return-value]
    })

    try:
        services[0].execute(
            AgentTask(task_id="req-2", role=AgentRole.NEWS, instruction="AI NEWS")
        )
    except TypeError as exc:
        assert str(exc) == "domain service handler must return str"
    else:
        raise AssertionError("expected TypeError")

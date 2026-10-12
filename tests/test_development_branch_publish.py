"""Tests for authenticated workflow-owned publication of autonomous branches."""
from types import SimpleNamespace

from core import line_development_runtime as runtime


def test_workflow_mode_defers_remote_push_to_authenticated_publisher(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_PUBLISH_VIA_WORKFLOW", "true")

    def forbidden_push(*args, **kwargs):
        raise AssertionError("runtime must not push when workflow publisher owns publication")

    monkeypatch.setattr(runtime.worker, "run", forbidden_push)

    ok, detail = runtime._push_development_branch("line-dev/12345")

    assert ok is True
    assert detail == "deferred_to_authenticated_workflow_publisher"


def test_non_workflow_mode_keeps_existing_push_behavior(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_PUBLISH_VIA_WORKFLOW", raising=False)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(runtime.worker, "run", fake_run)

    ok, detail = runtime._push_development_branch("line-dev/12345")

    assert ok is True
    assert detail == "development branch pushed"
    assert calls == [["git", "push", "--set-upstream", "origin", "line-dev/12345"]]


def test_non_workflow_mode_reports_push_failure(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_PUBLISH_VIA_WORKFLOW", raising=False)
    monkeypatch.setattr(
        runtime.worker,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=128, stderr="authentication unavailable", stdout=""),
    )

    ok, detail = runtime._push_development_branch("line-dev/12345")

    assert ok is False
    assert detail == "authentication unavailable"

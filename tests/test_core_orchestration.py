import pytest

from core.gateway import AIRequest, AIResponse
from core.orchestration import ExternalWorkflow, WorkflowResult


def test_external_workflow_adapts_string_response():
    workflow = ExternalWorkflow(lambda request: "calendar updated")

    result = workflow.handle(AIRequest("u1", "予定を追加", channel="line"))

    assert result == WorkflowResult(
        handled=True,
        response=AIResponse(text="calendar updated"),
    )


def test_external_workflow_keeps_ai_response():
    expected = AIResponse(text="done", metadata={"integration": "calendar"})
    workflow = ExternalWorkflow(lambda request: expected)

    assert workflow.handle(AIRequest("u1", "予定", channel="web")).response == expected


def test_external_workflow_rejects_invalid_handler():
    with pytest.raises(TypeError, match="handler must be callable"):
        ExternalWorkflow(object())


def test_external_workflow_rejects_invalid_request():
    workflow = ExternalWorkflow(lambda request: "ok")

    with pytest.raises(TypeError, match="AIRequest"):
        workflow.handle(object())


def test_external_workflow_rejects_invalid_result():
    workflow = ExternalWorkflow(lambda request: object())

    with pytest.raises(TypeError, match="AIResponse or str"):
        workflow.handle(AIRequest("u1", "hi", channel="line"))

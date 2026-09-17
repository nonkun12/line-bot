from __future__ import annotations

from pathlib import Path

from scripts.run_self_improvement_observer import build_report, run_observer


def test_build_report_preserves_runtime_failure_facts() -> None:
    report = build_report(
        {
            "failed_task_id": "tester-1",
            "error": "pytest failed",
            "rounds": "2",
            "repair_attempts": "1",
            "integration_ready": False,
        }
    )

    assert report.failed_task_id == "tester-1"
    assert report.error == "pytest failed"
    assert report.rounds == 2
    assert report.repair_attempts == 1
    assert report.integration_ready is False
    assert report.success is False


def test_observer_writes_analysis_artifact_without_auto_approval(tmp_path: Path) -> None:
    def fake_model(_prompt: str) -> str:
        return "bounded analysis"

    output = tmp_path / "observer.json"
    result = run_observer(
        {
            "objective": "repair recurring failures",
            "failed_task_id": "tester-1",
            "error": "pytest failed",
            "rounds": 1,
            "repair_attempts": 1,
            "integration_ready": False,
        },
        output_path=output,
        model_call=fake_model,
    )

    assert result["analysis_success"] is True
    assert result["analysis_agent_count"] == 3
    assert result["approved_for_pipeline"] is False
    assert output.exists()

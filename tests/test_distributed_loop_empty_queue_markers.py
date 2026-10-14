from pathlib import Path


def test_postrun_accepts_current_and_legacy_empty_queue_reasons():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-loop-postrun.yml"
    ).read_text(encoding="utf-8")

    assert '"- 結果理由: queue_empty"' in workflow
    assert '"- 結果理由: queue_exhausted_no_tasks"' in workflow
    assert "Queue-empty report conflicts with task result evidence." in workflow

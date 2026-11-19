from scripts.distributed_loop_chain import decide_chain


def _report(result="PASS", progress="1/4"):
    return (
        "# 分散Loop 終了報告\n"
        f"- 結果: **{result}**\n"
        f"- キュー進捗: {progress}\n"
    )


def _rows(status="PASS"):
    return [{"task_id": "job-001", "status": status}]


def test_chain_continues_only_when_passed_work_remains():
    result = decide_chain(
        _report(),
        _rows(),
        run_conclusion="success",
        continuation_depth=0,
    )
    assert result["continue"] is True
    assert result["next_depth"] == 1
    assert result["queue_completed"] == 1
    assert result["queue_total"] == 4


def test_chain_stops_when_queue_is_drained():
    result = decide_chain(
        _report(progress="4/4"),
        _rows(),
        run_conclusion="success",
        continuation_depth=0,
    )
    assert result["continue"] is False
    assert result["reason"] == "queue_drained"


def test_chain_stops_for_failed_or_blocked_task():
    for status in ("FAIL", "BLOCKED", "NOT_RUN", "UNKNOWN"):
        result = decide_chain(
            _report(),
            _rows(status),
            run_conclusion="success",
            continuation_depth=0,
        )
        assert result["continue"] is False


def test_chain_stops_when_workflow_failed_or_kill_switch_enabled():
    assert not decide_chain(
        _report(), _rows(), run_conclusion="failure", continuation_depth=0
    )["continue"]
    assert not decide_chain(
        _report(), _rows(), run_conclusion="success", continuation_depth=0,
        kill_switch=True,
    )["continue"]


def test_chain_has_a_hard_depth_limit():
    result = decide_chain(
        _report(), _rows(), run_conclusion="success", continuation_depth=12
    )
    assert result["continue"] is False
    assert result["reason"] == "continuation_depth_limit"


def test_chain_fails_closed_on_missing_or_invalid_progress_and_identity():
    for report in ("", _report(progress="bad"), _report(progress="5/4")):
        assert not decide_chain(
            report, _rows(), run_conclusion="success", continuation_depth=0
        )["continue"]
    assert not decide_chain(
        _report(),
        [{"task_id": "", "status": "PASS"}],
        run_conclusion="success",
        continuation_depth=0,
    )["continue"]

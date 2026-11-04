import goal_job_review


def _record():
    return {
        "goal_id": "review-goal",
        "goal": {"success_criteria": [{"id": "music"}, {"id": "visual"}]},
        "criterion_results": {"music": "FAIL", "visual": "FAIL"},
    }


def test_review_requires_independent_evaluator(monkeypatch):
    monkeypatch.setattr(goal_job_review.goal_job_store, "get_goal", lambda _goal: _record())
    result = goal_job_review.review_completed_goal("review-goal", evaluator=None)
    assert result == {"decision": "HOLD", "reason": "independent_evaluator_required"}


def test_review_waits_until_child_has_completed(monkeypatch):
    monkeypatch.setattr(goal_job_review.goal_job_store, "get_goal", lambda _goal: _record())
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "get_goal_child_jobs",
        lambda _goal: [{"status": "pending"}],
    )
    called = []
    result = goal_job_review.review_completed_goal(
        "review-goal",
        evaluator=lambda *_args: called.append(True) or {"music": "PASS", "visual": "PASS"},
    )
    assert result["reason"] == "no_completed_child_evidence"
    assert called == []


def test_review_requires_complete_criterion_map(monkeypatch):
    monkeypatch.setattr(goal_job_review.goal_job_store, "get_goal", lambda _goal: _record())
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "get_goal_child_jobs",
        lambda _goal: [{"status": "completed"}],
    )
    result = goal_job_review.review_completed_goal(
        "review-goal", evaluator=lambda *_args: {"music": "PASS"}
    )
    assert result["reason"] == "review_result_must_cover_all_criteria"


def test_review_persists_all_pass_before_advancing_once(monkeypatch):
    monkeypatch.setattr(goal_job_review.goal_job_store, "get_goal", lambda _goal: _record())
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "get_goal_child_jobs",
        lambda _goal: [{"status": "completed", "job_id": 12}],
    )
    updates = []
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "update_goal_evidence",
        lambda _goal, result: updates.append(result) or {
            "criterion_results": result,
        },
    )
    advances = []
    monkeypatch.setattr(
        goal_job_review, "advance_goal",
        lambda _goal, **kwargs: advances.append((_goal, kwargs)) or {
            "decision": "CHILD_JOB_QUEUED",
        },
    )
    result = goal_job_review.review_completed_goal(
        "review-goal",
        evaluator=lambda _record, children: (
            {"music": "PASS", "visual": "PASS"}
            if children[0]["job_id"] == 12 else {}
        ),
    )
    assert result["decision"] == "CHILD_JOB_QUEUED"
    assert result["reviewed"] is True
    assert updates == [{"music": "PASS", "visual": "PASS"}]
    assert len(advances) == 1


def test_review_does_not_advance_on_failed_criterion(monkeypatch):
    monkeypatch.setattr(goal_job_review.goal_job_store, "get_goal", lambda _goal: _record())
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "get_goal_child_jobs",
        lambda _goal: [{"status": "completed"}],
    )
    monkeypatch.setattr(
        goal_job_review.goal_job_store, "update_goal_evidence",
        lambda _goal, result: {"criterion_results": result},
    )
    monkeypatch.setattr(
        goal_job_review, "advance_goal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not advance")),
    )
    result = goal_job_review.review_completed_goal(
        "review-goal",
        evaluator=lambda *_args: {"music": "PASS", "visual": "UNKNOWN"},
    )
    assert result["reason"] == "independent_review_not_passed"

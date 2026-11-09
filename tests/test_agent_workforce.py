from core.agent_workforce import AgentWorkforce


def test_idle_agent_is_visible_and_becomes_ready_after_heartbeat(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("english", "line_runtime", ["vocabulary"])
    workforce.enqueue("word-cycle", ["vocabulary"], "Draft a candidate", approval_required=False)

    assert workforce.agents()[0].idle_reason == "NO_HEARTBEAT_OR_OFFLINE"
    assert workforce.heartbeat("english")
    assert workforce.agents()[0].idle_reason == "READY_FOR_ASSIGNMENT"


def test_capability_match_assigns_work_and_records_evidence(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("rea", "review_runtime", ["read-only-review"])
    workforce.heartbeat("rea")
    workforce.enqueue("review-1", ["read-only-review"], "Review evidence", approval_required=False)

    task = workforce.claim("rea")
    assert task is not None
    assert task.task_id == "review-1"
    assert task.status == "ASSIGNED"
    assert task.attempt_token
    assert workforce.start("review-1", "rea", attempt_token=task.attempt_token)
    assert workforce.finish("review-1", "rea", attempt_token=task.attempt_token, status="PASS", evidence="review-report-sha:abc")
    assert workforce.agents()[0].idle_reason == "NO_MATCHING_APPROVED_WORK"


def test_unapproved_task_cannot_be_claimed(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("english", "line_runtime", ["vocabulary"])
    workforce.heartbeat("english")
    workforce.enqueue("protected", ["vocabulary"], "Do not auto-adopt")

    assert workforce.claim("english") is None
    assert workforce.approve("protected")
    assert workforce.claim("english") is not None


def test_wrong_capability_and_offline_agent_do_not_claim(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("muse", "cloud_candidate", ["media"])
    workforce.enqueue("vocab", ["vocabulary"], "Draft", approval_required=False)
    assert workforce.claim("muse") is None
    assert workforce.heartbeat("muse")
    assert workforce.claim("muse") is None
    assert workforce.agents()[0].idle_reason == "NO_MATCHING_APPROVED_WORK"


def test_interrupted_task_is_requeued_without_false_pass(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("hermes", "mac_local", ["desktop"])
    workforce.heartbeat("hermes")
    workforce.enqueue("local-task", ["desktop"], "Inspect local app", approval_required=False)
    task = workforce.claim("hermes")
    assert task is not None
    assert workforce.start("local-task", "hermes", attempt_token=task.attempt_token)
    assert workforce.recover("local-task")
    recovered = workforce.claim("hermes")
    assert recovered is not None and recovered.status == "ASSIGNED"
    assert recovered.attempt_token != task.attempt_token


def test_terminal_state_requires_evidence_and_cannot_be_forged_by_other_agent(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("english", "line_runtime", ["vocabulary"])
    workforce.heartbeat("english")
    workforce.enqueue("task", ["vocabulary"], "Draft", approval_required=False)
    task = workforce.claim("english")
    assert task is not None
    assert workforce.start("task", "english", attempt_token=task.attempt_token)
    assert not workforce.finish("task", "other", attempt_token=task.attempt_token, status="PASS", evidence="fake")
    assert not workforce.finish("task", "english", attempt_token=task.attempt_token, status="PASS", evidence="")
    assert workforce.finish("task", "english", attempt_token=task.attempt_token, status="PASS", evidence="sha256:abc")


def test_recovered_attempt_token_cannot_finish_reassigned_task(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("english", "line_runtime", ["vocabulary"])
    workforce.heartbeat("english")
    workforce.enqueue("retry", ["vocabulary"], "Draft", approval_required=False)

    first = workforce.claim("english")
    assert first is not None
    assert workforce.start("retry", "english", attempt_token=first.attempt_token)
    assert workforce.recover("retry")
    assert workforce.heartbeat("english")
    second = workforce.claim("english")
    assert second is not None and second.attempt_token != first.attempt_token
    assert workforce.start("retry", "english", attempt_token=second.attempt_token)

    assert not workforce.finish("retry", "english", attempt_token=first.attempt_token,
                                status="PASS", evidence="stale-worker-result")
    assert workforce.finish("retry", "english", attempt_token=second.attempt_token,
                             status="PASS", evidence="current-attempt-report-sha:abc")

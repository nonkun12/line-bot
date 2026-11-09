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
    assert workforce.start("review-1", "rea")
    assert workforce.finish("review-1", "rea", status="PASS", evidence="review-report-sha:abc")
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
    assert workforce.claim("hermes") is not None
    assert workforce.start("local-task", "hermes")
    assert workforce.recover("local-task")
    assert workforce.claim("hermes").status == "ASSIGNED"


def test_terminal_state_requires_evidence_and_cannot_be_forged_by_other_agent(tmp_path):
    workforce = AgentWorkforce(tmp_path / "agents.db")
    workforce.register("english", "line_runtime", ["vocabulary"])
    workforce.heartbeat("english")
    workforce.enqueue("task", ["vocabulary"], "Draft", approval_required=False)
    workforce.claim("english")
    assert not workforce.finish("task", "other", status="PASS", evidence="fake")
    assert not workforce.finish("task", "english", status="PASS", evidence="")
    assert workforce.start("task", "english")
    assert workforce.finish("task", "english", status="PASS", evidence="sha256:abc")

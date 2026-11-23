from scripts.goal_state_store import GoalStateStore
import pytest

def goal():
    return {"goal_id":"g1","objective":"bounded","acceptance_criteria":[{"id":"c1","verified":False}],
      "safety_gate":True,"kill_switch":False,"tasks":[
       {"task_id":"t1","status":"PENDING","kind":"TEST","execution_authorized":True,"allowed_paths":["tests/"]},
       {"task_id":"t2","status":"PENDING","kind":"READ_ONLY","execution_authorized":True,"allowed_paths":[]}]}

def evidence(task_id):
    return {"task_id":task_id,"verified":True,"evidence_sha":"a"*40,
      "verification_ref":"run:123","completed_at":"2026-11-19T00:00:00+00:00"}

def test_claim_is_single_and_durable(tmp_path):
    path=tmp_path/"goal.db"; store=GoalStateStore(path); store.create(goal())
    assert store.claim_next("g1")["decision"]=="CLAIMED"
    reopened=GoalStateStore(path)
    assert reopened.read("g1")[1]["tasks"][0]["status"]=="IN_PROGRESS"
    assert reopened.claim_next("g1")["reason"]=="in_flight_task_requires_reconciliation"

def test_completion_requires_task_bound_verified_evidence(tmp_path):
    store=GoalStateStore(tmp_path/"goal.db"); store.create(goal()); store.claim_next("g1")
    with pytest.raises(ValueError):
        store.record_result("g1","t1",status="COMPLETED",completion_evidence={"task_id":"wrong"})

def test_only_claimed_task_can_finish(tmp_path):
    store=GoalStateStore(tmp_path/"goal.db"); store.create(goal())
    with pytest.raises(RuntimeError):
        store.record_result("g1","t1",status="COMPLETED",completion_evidence=evidence("t1"))

def test_verified_result_advances_revision(tmp_path):
    store=GoalStateStore(tmp_path/"goal.db"); store.create(goal()); store.claim_next("g1")
    assert store.record_result("g1","t1",status="COMPLETED",completion_evidence=evidence("t1"))==2
    rev,state=store.read("g1"); assert rev==2 and state["tasks"][0]["status"]=="COMPLETED"

def test_stale_compare_and_swap_rejected(tmp_path):
    store=GoalStateStore(tmp_path/"goal.db"); state=goal(); store.create(state)
    with pytest.raises(RuntimeError,match="revision conflict"):
        store.compare_and_swap("g1",1,state)

def test_kill_switch_blocks_claim(tmp_path):
    store=GoalStateStore(tmp_path/"goal.db"); state=goal(); store.create(state)
    state["kill_switch"]=True; store.compare_and_swap("g1",0,state)
    assert store.claim_next("g1")["decision"]=="HOLD"


def test_importing_inflight_goal_preserves_hold_for_reconciliation(tmp_path):
    path = tmp_path / "goal.db"
    store = GoalStateStore(path)
    store.create(goal())
    store.claim_next("g1")
    revision, inflight = store.read("g1")
    reopened = GoalStateStore(tmp_path / "reopened.db")
    reopened.create(inflight)
    assert reopened.claim_next("g1")["reason"] == "in_flight_task_requires_reconciliation"


@pytest.mark.parametrize("invalid_status", [["FAIL"], {"status": "FAIL"}, 1])
def test_failure_evidence_rejects_non_string_result_status(tmp_path, invalid_status):
    store = GoalStateStore(tmp_path / "goal.db")
    store.create(goal())
    store.claim_next("g1")
    with pytest.raises(ValueError, match="failure evidence result status invalid"):
        store.record_result(
            "g1", "t1", status="HELD",
            failure_evidence={
                "stage": "child_runner",
                "reason_code": "runner_nonzero_exit",
                "result_status": invalid_status,
            },
        )
    assert store.read("g1")[1]["tasks"][0]["status"] == "IN_PROGRESS"

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
import scripts.goal_runtime_bridge as bridge

def _inputs(tmp_path: Path):
    task = {"id":"approved-test-task","instruction":"Run one bounded test-only task",
            "allowed_paths":["tests/test_example.py"]}
    queue, catalog, state, results, stop = [tmp_path / n for n in
        ("queue.json","catalog.json","state.json","results.jsonl","stop")]
    queue.write_text(json.dumps({"version":1,"max_tasks_per_run":1,"tasks":[task]}))
    catalog.write_text(json.dumps({"version":1,"max_additions_per_run":1,
        "tasks":[{**task,"execution_approved":True}]}))
    state.write_text(json.dumps({"version":1,"completed":[]}))
    return queue,catalog,state,results,stop

def test_only_exact_approved_catalog_tasks_enter_goal(tmp_path):
    queue,catalog,state,results,stop = _inputs(tmp_path)
    assert bridge._authorized_queue(queue,catalog,set())[0]["execution_authorized"] is True
    data=json.loads(catalog.read_text()); data["tasks"][0]["execution_approved"]=False
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="not_explicitly_approved"):
        bridge._authorized_queue(queue,catalog,set())

def test_bridge_runs_one_guarded_task_and_persists_verified_goal(tmp_path,monkeypatch):
    queue,catalog,state,results,stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE",str(queue))
    monkeypatch.setattr(bridge,"ROOT",tmp_path)
    monkeypatch.setattr(bridge,"_valid_success",lambda row,task_id: row.get("task_id")==task_id)
    produced="b"*40
    def fake_run(command,*,cwd,env,check):
        assert env["AUTONOMOUS_LOOP_TASK_QUEUE"] != str(queue)
        assert command[command.index("--max-tasks")+1] == "1"
        with results.open("a") as stream:
            stream.write(json.dumps({"task_id":"approved-test-task","status":"PASS","exit_code":0,
                "base_sha":"a"*40,"produced_sha":produced,"run_nonce":"nonce-1"})+"\n")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(bridge.subprocess,"run",fake_run)
    goal_output=tmp_path/"goal-pending.json"
    args=SimpleNamespace(catalog=catalog,state=state,results=results,stop_file=stop,
                         goal_state_output=goal_output,max_tasks=1)
    assert bridge.run(args)==0
    saved=json.loads(state.read_text()); goal=json.loads(goal_output.read_text())
    assert saved["completed"]==["approved-test-task"]
    assert "goal_autopilot" not in saved
    assert goal["tasks"][0]["status"]=="COMPLETED"
    assert goal["tasks"][0]["completion_evidence"]["task_id"]=="approved-test-task"
    assert goal["acceptance_criteria"][0]["verified"] is True
    assert goal["acceptance_criteria"][0]["evidence_ref"]=="commit:"+produced

def test_failed_guarded_task_is_held_and_not_retried(tmp_path,monkeypatch):
    queue,catalog,state,results,stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE",str(queue))
    monkeypatch.setattr(bridge,"ROOT",tmp_path)
    monkeypatch.setattr(bridge,"_valid_success",lambda row,task_id: False)
    def fake_run(command,*,cwd,env,check):
        results.write_text(json.dumps({"task_id":"approved-test-task","status":"FAIL","exit_code":1})+"\n")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(bridge.subprocess,"run",fake_run)
    goal_output=tmp_path/"goal-pending.json"
    args=SimpleNamespace(catalog=catalog,state=state,results=results,stop_file=stop,
                         goal_state_output=goal_output,max_tasks=1)
    assert bridge.run(args)==1
    assert goal_output.exists()
    assert json.loads(goal_output.read_text())["tasks"][0]["status"] == "HELD"
    assert "goal_autopilot" not in json.loads(state.read_text())


def test_explicit_resume_reopens_only_approved_held_task(tmp_path):
    queue, catalog, state_path, results, stop = _inputs(tmp_path)
    approved = bridge._authorized_queue(queue, catalog, set())
    held_goal = {
        "goal_id": bridge.GOAL_ID,
        "objective": "bounded",
        "acceptance_criteria": [{"id": "complete", "verified": False}],
        "safety_gate": True,
        "kill_switch": False,
        "tasks": [{**approved[0], "status": "HELD", "hold_reason": "review"}],
    }
    store = bridge.GoalStateStore(tmp_path / "resume.db")
    loaded = bridge._load_goal(store, {"goal_autopilot": held_goal}, approved, set(), "approved-test-task")
    assert loaded is not None
    assert loaded[1]["tasks"][0]["status"] == "PENDING"


def test_resume_cannot_reopen_task_outside_approved_queue(tmp_path):
    queue, catalog, state_path, results, stop = _inputs(tmp_path)
    approved = bridge._authorized_queue(queue, catalog, set())
    held_goal = {
        "goal_id": bridge.GOAL_ID,
        "objective": "bounded",
        "acceptance_criteria": [{"id": "complete", "verified": False}],
        "safety_gate": True,
        "kill_switch": False,
        "tasks": [{**approved[0], "status": "HELD"}],
    }
    store = bridge.GoalStateStore(tmp_path / "resume.db")
    with pytest.raises(ValueError, match="resume_task_not_in_current_approved_queue"):
        bridge._load_goal(store, {"goal_autopilot": held_goal}, [], set(), "approved-test-task")



def test_approval_dispatch_claims_only_the_bound_task(tmp_path, monkeypatch):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    queue_data = json.loads(queue.read_text())
    catalog_data = json.loads(catalog.read_text())
    second = {
        "id": "approved-test-task-2",
        "instruction": "Run the second bounded test-only task",
        "allowed_paths": ["tests/test_second.py"],
    }
    queue_data["tasks"].append(second)
    catalog_data["tasks"].append({**second, "execution_approved": True})
    queue.write_text(json.dumps(queue_data))
    catalog.write_text(json.dumps(catalog_data))
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "_valid_success", lambda row, task_id: row.get("task_id") == task_id)

    def fake_run(command, *, cwd, env, check):
        child_queue = json.loads(Path(env["AUTONOMOUS_LOOP_TASK_QUEUE"]).read_text())
        selected_id = child_queue["tasks"][0]["id"]
        assert selected_id == "approved-test-task-2"
        results.write_text(json.dumps({
            "task_id": selected_id, "status": "PASS", "exit_code": 0,
            "base_sha": "a" * 40, "produced_sha": "b" * 40, "run_nonce": "nonce-2",
        }) + "\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    args = SimpleNamespace(
        catalog=catalog, state=state, results=results, stop_file=stop,
        goal_state_output=tmp_path / "goal-pending.json", max_tasks=1,
    )

    assert bridge.run(
        args,
        approval_hmac_secret="test-only-line-approval-secret-at-least-32-bytes",
        approval_required=True,
        approval_task_id="approved-test-task-2",
    ) == 0

    goal = json.loads(args.goal_state_output.read_text())
    statuses = {task["task_id"]: task["status"] for task in goal["tasks"]}
    assert statuses == {
        "approved-test-task": "PENDING",
        "approved-test-task-2": "COMPLETED",
    }


def test_approval_dispatch_without_task_binding_fails_before_claim(tmp_path, monkeypatch):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(
        bridge.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("must not launch an unbound approval"),
    )
    args = SimpleNamespace(
        catalog=catalog, state=state, results=results, stop_file=stop,
        goal_state_output=tmp_path / "goal-pending.json", max_tasks=1,
    )

    assert bridge.run(
        args,
        approval_hmac_secret="test-only-line-approval-secret-at-least-32-bytes",
        approval_required=True,
        approval_task_id="",
    ) == 80
    assert not results.exists()

def test_partial_workflow_failure_does_not_durably_complete_unpublished_prior_task(tmp_path, monkeypatch):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    queue_data = json.loads(queue.read_text())
    catalog_data = json.loads(catalog.read_text())
    second = {
        "id": "approved-test-task-2",
        "instruction": "Run a second bounded test-only task",
        "allowed_paths": ["tests/test_second.py"],
    }
    queue_data["tasks"].append(second)
    catalog_data["tasks"].append({**second, "execution_approved": True})
    queue.write_text(json.dumps(queue_data))
    catalog.write_text(json.dumps(catalog_data))
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "_valid_success", lambda row, task_id: row.get("status") == "PASS")
    calls = {"count": 0}

    def fake_run(command, *, cwd, env, check):
        calls["count"] += 1
        selected = json.loads(Path(env["AUTONOMOUS_LOOP_TASK_QUEUE"]).read_text())["tasks"][0]
        if calls["count"] == 1:
            row = {"task_id": selected["id"], "status": "PASS", "exit_code": 0,
                   "base_sha": "a" * 40, "produced_sha": "b" * 40, "run_nonce": "nonce-1"}
            with results.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            return SimpleNamespace(returncode=0)
        row = {"task_id": selected["id"], "status": "FAIL", "exit_code": 1}
        with results.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    goal_output = tmp_path / "goal-pending.json"
    args = SimpleNamespace(catalog=catalog, state=state, results=results, stop_file=stop,
                           goal_state_output=goal_output, max_tasks=2)
    assert bridge.run(args) == 1
    goal = json.loads(goal_output.read_text())
    statuses = {task["task_id"]: task["status"] for task in goal["tasks"]}
    assert statuses == {"approved-test-task": "PENDING", "approved-test-task-2": "HELD"}



@pytest.mark.parametrize("sentinel", [78, 79])
def test_guarded_runner_sentinel_outcome_is_preserved_without_synthetic_failure(
    tmp_path, monkeypatch, sentinel
):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)

    def fake_run(command, *, cwd, env, check):
        return SimpleNamespace(returncode=sentinel)

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    goal_output = tmp_path / "goal-pending.json"
    args = SimpleNamespace(
        catalog=catalog,
        state=state,
        results=results,
        stop_file=stop,
        goal_state_output=goal_output,
        max_tasks=1,
    )

    assert bridge.run(args) == sentinel
    assert not results.exists()
    goal = json.loads(goal_output.read_text())
    assert goal["tasks"][0]["status"] == "HELD"
    assert goal["tasks"][0]["hold_reason"] == "guarded_runtime_or_evidence_gate_failed"


@pytest.mark.parametrize(
    "claim_result",
    [
        {"decision": "HOLD", "reason": "requested_task_not_pending"},
        {"decision": "COMPLETE", "reason": "all_acceptance_criteria_verified"},
    ],
)
def test_approved_nonpending_target_returns_blocked_not_success(tmp_path, monkeypatch, claim_result):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(
        bridge.GoalStateStore,
        "claim_next",
        lambda self, goal_id, task_id=None: {
            **claim_result, "task_id": task_id
        },
    )
    args = SimpleNamespace(
        catalog=catalog, state=state, results=results, stop_file=stop,
        goal_state_output=tmp_path / "goal-pending.json", max_tasks=1,
    )

    result = bridge.run(
        args, approval_hmac_secret="x" * 40, approval_required=True,
        approval_task_id="approved-test-task",
    )

    assert result == 80
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    assert rows[-1]["status"] == "BLOCKED"
    assert rows[-1]["task_id"] == "approved-test-task"
    assert rows[-1]["failure_reason"] in {
        "requested_task_not_pending", "all_acceptance_criteria_verified",
        "approved_task_already_complete",
    }


def test_workflow_returns_nonzero_for_nonclaimable_explicit_approval():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index('          if [ "$loop_rc" -eq 79 ]; then')
    end = workflow.index('          exit "$loop_rc"', start)
    shell_block = workflow[start:end]
    script = (
        'loop_rc=79\n'
        'GOAL_APPROVAL_REQUIRED=true\n'
        + shell_block
        + '\nexit "$loop_rc"\n'
    )

    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert result.returncode == 80
    assert "explicitly approved task is not claimable" in result.stdout



def test_unapproved_scheduled_attempt_returns_task_to_pending(tmp_path, monkeypatch):
    queue, catalog, state, results, stop = _inputs(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_QUEUE", str(queue))
    monkeypatch.setattr(bridge, "ROOT", tmp_path)

    def fake_run(command, *, cwd, env, check):
        results.write_text(json.dumps({
            "task_id": "approved-test-task",
            "status": "BLOCKED",
            "exit_code": 81,
            "failure_reason": "independent_execution_approval_missing_or_invalid",
        }) + "\n")
        return SimpleNamespace(returncode=81)

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    goal_output = tmp_path / "goal-pending.json"
    args = SimpleNamespace(
        catalog=catalog, state=state, results=results, stop_file=stop,
        goal_state_output=goal_output, max_tasks=1,
    )

    assert bridge.run(args, approval_required=False) == 80
    goal = json.loads(goal_output.read_text())
    assert goal["tasks"][0]["status"] == "PENDING"
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    assert rows[-1]["status"] == "BLOCKED"
    assert rows[-1]["failure_reason"] == "execution_approval_required"

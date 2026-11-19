import json
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
    assert not goal_output.exists()
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

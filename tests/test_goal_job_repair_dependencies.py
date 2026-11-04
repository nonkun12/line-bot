import db
import goal_job_store


def test_verified_repair_satisfies_downstream_dependency(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-repair-dependency.sqlite"))
    db.init_db()
    goal = {
        "goal_id": "goal-repair-dependency",
        "objective": "Complete sequential creative production plans",
        "success_criteria": [
            {"id": "phase-one", "description": "Phase one plan is verified"},
            {"id": "phase-two", "description": "Phase two plan is verified"},
        ],
        "jobs": [
            {
                "id": "phase-one-initial",
                "criterion_id": "phase-one",
                "stage": "design",
                "instruction": "Create phase one plan.",
                "allowed_paths": ["docs/phase-one.md"],
                "depends_on": [],
            },
            {
                "id": "phase-two",
                "criterion_id": "phase-two",
                "stage": "design",
                "instruction": "Create phase two plan.",
                "allowed_paths": ["docs/phase-two.md"],
                "depends_on": ["phase-one-initial"],
            },
        ],
    }
    grant = {
        "grant_id": "grant-repair-dependency",
        "goal_id": "goal-repair-dependency",
        "active": True,
        "approved_by": "U-test",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 5,
        "allowed_stages": ["design"],
        "allowed_path_prefixes": ["docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }
    goal_job_store.create_goal(goal, "U-test", grant)
    initial = goal_job_store.persist_child_job("goal-repair-dependency", goal["jobs"][0])
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='failed' WHERE id=?", (initial["job_id"],))

    repair = {
        "id": "phase-one-repair",
        "criterion_id": "phase-one",
        "stage": "design",
        "instruction": "Create a revised phase one plan.",
        "allowed_paths": ["docs/phase-one-repair.md"],
        "depends_on": [],
    }
    goal_job_store.register_child_job_definition("goal-repair-dependency", repair)
    repaired = goal_job_store.persist_child_job("goal-repair-dependency", repair)
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (repaired["job_id"],))
    goal_job_store.save_child_evidence(
        repaired["job_id"],
        {"checks": [{"name": "review", "status": "PASS", "source": "independent review"}]},
    )
    results = goal_job_store.evaluate_completed_goal_criteria("goal-repair-dependency")
    assert results == {"phase-one": "PASS", "phase-two": "FAIL"}
    goal_job_store.update_goal_evidence("goal-repair-dependency", results)
    states = goal_job_store.get_goal_job_states("goal-repair-dependency")
    assert states["phase-one-initial"] == "done"

    next_job = goal_job_store.persist_child_job("goal-repair-dependency", goal["jobs"][1])
    assert next_job["status"] == "pending"
    assert next_job["parent_job_id"] == initial["job_id"]

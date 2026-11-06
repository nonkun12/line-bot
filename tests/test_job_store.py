import db
import job_store


def test_create_get_and_claim_job(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "夜間にテスト", source="test")
    job = job_store.get_job(job_id)

    assert job["status"] == "pending"
    assert job["source"] == "test"
    assert job["retry_count"] == 0
    assert job["max_retries"] == 3

    claimed = job_store.claim_pending_job()
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert job_store.claim_pending_job() is None


def test_checkpoint_and_job_update(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "checkpoint test")
    checkpoint_id = job_store.save_checkpoint(
        job_id, "requirements", "completed", '{"ok": true}'
    )
    assert checkpoint_id is not None

    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["job_id"] == job_id
    assert checkpoint["step_name"] == "requirements"
    assert checkpoint["step_status"] == "completed"
    assert checkpoint["output_snapshot"] == '{"ok": true}'

    assert job_store.update_job(job_id, status="done", result="success") is True
    job = job_store.get_job(job_id)
    assert job["status"] == "done"
    assert job["result"] == "success"


def test_parent_job_and_retry_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    parent_id = job_store.create_job("U-test", "parent")
    child_id = job_store.create_job(
        "U-test",
        "child",
        source="derived",
        parent_job_id=parent_id,
        max_retries=5,
    )

    child = job_store.get_job(child_id)
    assert child["parent_job_id"] == parent_id
    assert child["max_retries"] == 5


def test_create_job_chain_links_steps_and_releases_them_in_order(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    ids = job_store.create_job_chain(
        "U-goal",
        [
            {"message": "調査", "job_type": "goal_research"},
            {"message": "実装", "job_type": "goal_implementation"},
            {"message": "検証", "job_type": "goal_verification"},
        ],
    )

    assert len(ids) == 3
    assert [job_store.get_job(job_id)["parent_job_id"] for job_id in ids] == [None, ids[0], ids[1]]
    assert job_store.claim_pending_job()["id"] == ids[0]
    assert job_store.claim_pending_job() is None

    assert job_store.update_job(ids[0], status="done", result="research complete")
    assert job_store.claim_pending_job()["id"] == ids[1]
    assert job_store.claim_pending_job() is None

    assert job_store.update_job(ids[1], status="completed", result="implementation complete")
    assert job_store.claim_pending_job()["id"] == ids[2]


def test_failed_parent_keeps_descendant_jobs_unclaimable(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    ids = job_store.create_job_chain(
        "U-goal",
        [{"message": "step 1"}, {"message": "step 2"}],
    )
    assert job_store.claim_pending_job()["id"] == ids[0]
    assert job_store.update_job(ids[0], status="failed", last_error="blocked")
    assert job_store.claim_pending_job() is None
    assert job_store.get_job(ids[1])["status"] == "pending"


def test_invalid_job_chain_is_rejected_without_partial_inserts(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    for steps in (
        [],
        [{"message": "valid"}, {"message": "bad", "unexpected": True}],
        [{"message": "valid", "max_retries": True}],
        [{"message": "x" * 4001}],
    ):
        try:
            job_store.create_job_chain("U-goal", steps)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid chain should be rejected")
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 0


def test_typed_claim_respects_goal_chain_parent_dependency(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    ids = job_store.create_job_chain(
        "U-goal",
        [
            {"message": "research", "job_type": "goal_research"},
            {"message": "build", "job_type": "goal_build"},
        ],
    )
    assert db.claim_pending_job_by_type("goal_build") is None
    parent = db.claim_pending_job_by_type("goal_research")
    assert parent["id"] == ids[0]
    assert db.complete_claimed_job(
        parent["id"], parent["claim_token"], success=True, result="done"
    )
    child = db.claim_pending_job_by_type("goal_build")
    assert child["id"] == ids[1]

import db


def _start_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.sqlite"))
    db.init_db()
    job_id = db.create_job("U-test", "development", job_type="development")
    claimed = db.claim_pending_job(worker_id="worker-a", lease_seconds=300)
    assert claimed["id"] == job_id
    return job_id


def test_publish_aborts_before_push_when_lease_is_lost(tmp_path, monkeypatch):
    from agents.publish import node as publish

    job_id = _start_job(tmp_path, monkeypatch)
    monkeypatch.setenv("AUTO_PUBLISH_JOB_BRANCH", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        publish,
        "_push_branch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("push must not run")),
    )
    monkeypatch.setattr(
        publish,
        "require_active_job_lease",
        lambda state: (_ for _ in ()).throw(RuntimeError("lease lost")),
    )

    result = publish.publish_node({
        "job_id": job_id,
        "worker_id": "worker-a",
        "workdir": str(tmp_path),
        "commit_result": {
            "committed": True,
            "hash": "abc123",
            "branch": f"worker/job-{job_id}",
        },
        "agent_results": {},
    })

    assert result["publish_result"]["published"] is False
    assert result["publish_result"]["error"] == "lease lost"


def test_merge_aborts_before_github_mutation_when_lease_is_lost(tmp_path, monkeypatch):
    from agents.merge import node as merge

    job_id = _start_job(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        merge,
        "get_pr_state",
        lambda number: {
            "number": number,
            "state": "open",
            "merged": False,
            "head_sha": "abc123",
            "head_branch": f"worker/job-{job_id}",
            "base_branch": "main",
        },
    )
    monkeypatch.setattr(
        merge,
        "require_active_job_lease",
        lambda state: (_ for _ in ()).throw(RuntimeError("lease lost")),
    )
    monkeypatch.setattr(
        merge.requests,
        "put",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("merge must not run")),
    )

    result = merge.merge_node({
        "job_id": job_id,
        "worker_id": "worker-a",
        "commit_result": {"committed": True, "hash": "abc123", "branch": f"worker/job-{job_id}"},
        "publish_result": {"published": True, "branch": f"worker/job-{job_id}", "pr": {"number": 42}},
        "agent_results": {},
    })

    assert result["merge_result"]["merged"] is False
    assert result["merge_result"]["error"] == "lease lost"


def test_deploy_aborts_before_render_trigger_when_lease_is_lost(tmp_path, monkeypatch):
    from agents.deploy import node as deploy

    job_id = _start_job(tmp_path, monkeypatch)
    monkeypatch.setenv("AUTO_DEPLOY", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        deploy,
        "check_pr_merged",
        lambda state: {
            "known": True,
            "merged": True,
            "number": 42,
            "merge_commit_sha": "merge123",
        },
    )
    monkeypatch.setattr(
        deploy,
        "require_active_job_lease",
        lambda state: (_ for _ in ()).throw(RuntimeError("lease lost")),
    )
    monkeypatch.setattr(
        deploy,
        "trigger_deploy",
        lambda: (_ for _ in ()).throw(AssertionError("deploy must not run")),
    )

    result = deploy.deploy_node({
        "job_id": job_id,
        "worker_id": "worker-a",
        "commit_result": {"committed": True, "hash": "abc123"},
        "publish_result": {"published": True, "pr": {"number": 42}},
        "agent_results": {},
    })

    assert result["deploy_result"]["deployed"] is False
    assert result["deploy_result"]["reason"] == "lease lost"

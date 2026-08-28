import db
import job_approvals
import job_worker


class Snapshot:
    def __init__(self, values=None, next_nodes=()):
        self.values = values or {}
        self.next = next_nodes


class ApprovalGraph:
    def __init__(self, next_after_invoke=("finalizer",)):
        self.snapshot = Snapshot(
            values={"request_id": "job-1"},
            next_nodes=("commit_agent",),
        )
        self.next_after_invoke = next_after_invoke
        self.invoke_count = 0

    def get_state(self, config):
        return self.snapshot

    def invoke(self, input_state, config):
        self.invoke_count += 1
        self.snapshot = Snapshot(
            values={"request_id": config["configurable"]["thread_id"]},
            next_nodes=self.next_after_invoke,
        )
        return self.snapshot.values


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_unapproved_commit_never_invokes_graph(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "approval")
    graph = ApprovalGraph()
    job = db.get_job(job_id)

    result = job_worker.execute_one_step(job, graph=graph)

    assert result["status"] == "waiting_approval"
    assert result["operation"] == "commit"
    assert graph.invoke_count == 0
    assert job_approvals.status(job_id, "commit") == "pending"


def test_approved_commit_is_consumed_and_only_deploy_waits_next(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "approval")
    job_approvals.request(job_id, "U-test", "commit")
    assert job_approvals.approve(job_id, "commit", "human") is True

    graph = ApprovalGraph(next_after_invoke=("deploy_agent",))
    job = db.get_job(job_id)

    result = job_worker.execute_one_step(job, graph=graph)

    assert graph.invoke_count == 1
    assert job_approvals.status(job_id, "commit") == "consumed"
    assert result["status"] == "waiting_approval"
    assert result["operation"] == "deploy"
    assert job_approvals.status(job_id, "deploy") == "pending"


def test_job_approval_does_not_cross_job_boundary(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_a = db.create_job("U-a", "a")
    job_b = db.create_job("U-b", "b")
    job_approvals.request(job_a, "U-a", "commit")
    job_approvals.request(job_b, "U-b", "commit")
    job_approvals.approve(job_a, "commit", "human")

    assert job_approvals.status(job_a, "commit") == "approved"
    assert job_approvals.status(job_b, "commit") == "pending"

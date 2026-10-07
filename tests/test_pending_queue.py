from core.pending_queue import PendingQueue


def test_unapproved_task_is_not_claimed(tmp_path):
    queue = PendingQueue(tmp_path / "queue.db")
    task_id = queue.enqueue("save this to Obsidian")
    assert queue.claim_next() is None
    assert queue.get(task_id).status == "PENDING"


def test_approved_task_is_claimed_and_can_finish(tmp_path):
    queue = PendingQueue(tmp_path / "queue.db")
    task_id = queue.enqueue("run Hermes task")
    assert queue.approve(task_id)
    task = queue.claim_next()
    assert task is not None
    assert task.task_id == task_id
    assert task.status == "RUNNING"

    assert queue.finish(task_id, status="PASS", result="verified", sha="abc123")
    finished = queue.get(task_id)
    assert finished.status == "PASS"
    assert finished.sha == "abc123"


def test_interrupted_running_task_returns_to_pending_not_success(tmp_path):
    queue = PendingQueue(tmp_path / "queue.db")
    task_id = queue.enqueue("continue later")
    assert queue.approve(task_id)
    assert queue.claim_next() is not None
    assert queue.recover_running(task_id)

    recovered = queue.get(task_id)
    assert recovered.status == "PENDING"
    assert recovered.retry_count == 1
    assert recovered.result is None


def test_terminal_state_cannot_be_finished_twice(tmp_path):
    queue = PendingQueue(tmp_path / "queue.db")
    task_id = queue.enqueue("one shot")
    assert queue.approve(task_id)
    assert queue.claim_next() is not None
    assert queue.finish(task_id, status="FAILED", error="test")
    assert not queue.finish(task_id, status="PASS", result="late")

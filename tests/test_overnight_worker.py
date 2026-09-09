from __future__ import annotations

import overnight_worker


def test_worker_loop_processes_multiple_cycles(monkeypatch):
    calls = []

    monkeypatch.setattr(overnight_worker.db, "init_db", lambda: calls.append("init"))
    monkeypatch.setattr(overnight_worker, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(overnight_worker, "MAX_CYCLES", 3)
    monkeypatch.setattr(overnight_worker, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(overnight_worker, "IDLE_BACKOFF_MAX_SECONDS", 0)

    def run_once():
        calls.append("run")
        return {"id": len([item for item in calls if item == "run"]), "status": "done"}

    overnight_worker.run_forever(run_once=run_once, sleep=lambda _seconds: calls.append("sleep"))

    assert calls == ["init", "run", "run", "run"]


def test_worker_loop_backs_off_when_queue_is_empty(monkeypatch):
    sleeps = []

    monkeypatch.setattr(overnight_worker.db, "init_db", lambda: None)
    monkeypatch.setattr(overnight_worker, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(overnight_worker, "MAX_CYCLES", 2)
    monkeypatch.setattr(overnight_worker, "POLL_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(overnight_worker, "IDLE_BACKOFF_MAX_SECONDS", 4)

    overnight_worker.run_forever(
        run_once=lambda: None,
        sleep=lambda seconds: sleeps.append(seconds),
    )

    assert sleeps == [1, 2]

from types import SimpleNamespace

import agents.sheets.autonomous_ledger as ledger


class FakeClient:
    def __init__(self, existing=None, response=None):
        self.existing = existing or []
        self.response = response or {"updates": {"updatedRows": 1}}
        self.appended = []

    def search_column(self, *args):
        return self.existing

    def append_row(self, *args):
        self.appended.append(args)
        return self.response

    def read_rows(self, *args):
        return [ledger.HEADERS]

    def update_row(self, *args):
        return {"updatedRows": 1}


def make_record(run_id="123"):
    return ledger.AutonomousRunRecord(
        timestamp="2026-09-23T03:00:00Z",
        run_id=run_id,
        task_id="scheduled-distributed-development",
        source="scheduler",
        agent="DistributedDevelopmentRuntime",
        task_summary="test",
        base_sha="base",
        produced_sha="produced",
        changed_files="app.py",
        pr_url="",
        tests_result="FAIL",
        verification_result="NOT_RUN",
        safety_gate_result="BLOCKED",
        merge_result="NOT_AUTO_MERGED",
        blocked_failed_reason="provider_error",
        next_action="review_failure",
    )


def test_append_once_records_when_google_accepts_one_row():
    client = FakeClient()
    assert ledger.append_once(client, make_record()) is True
    assert len(client.appended) == 1
    assert client.appended[0][1] == make_record().values()


def test_append_once_is_idempotent_for_existing_run_id():
    client = FakeClient(existing=[[None, "123"]])
    assert ledger.append_once(client, make_record("123")) is False
    assert client.appended == []


def test_append_once_rejects_unconfirmed_append():
    client = FakeClient(response={"updates": {"updatedRows": 0}})
    try:
        ledger.append_once(client, make_record("456"))
    except RuntimeError as exc:
        assert "updatedRows=0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_record_autonomous_run_retries_once(monkeypatch):
    calls = []

    class Factory:
        def __call__(self):
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("temporary Sheets failure")
            return FakeClient()

    monkeypatch.setattr(ledger, "GoogleSheetsClient", Factory())
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    monkeypatch.setenv("AUTONOMOUS_TIMESTAMP", "2026-09-23T03:00:00Z")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "scheduled-distributed-development")
    monkeypatch.setenv("DEV_INSTRUCTION", "test")

    assert ledger.record_autonomous_run() is True
    assert calls == [0, 1]

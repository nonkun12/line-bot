import agents.sheets.autonomous_ledger as ledger


class FakeClient:
    def __init__(self, existing=None, response=None, readback=None):
        self.existing = existing or []
        self.response = response or {
            "updates": {
                "updatedRows": 1,
                "updatedRange": "AutonomousDevelopment!A5:Q5",
            }
        }
        self.readback = readback
        self.appended = []
        self.read_ranges = []

    def search_column(self, *args):
        return self.existing

    def append_row(self, *args):
        self.appended.append(args)
        return self.response

    def read_rows(self, range_name):
        self.read_ranges.append(range_name)
        if range_name == "AutonomousDevelopment!A5:Q5" and self.readback is not None:
            return self.readback
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


def test_append_once_records_and_reads_back_exact_row():
    record = make_record()
    client = FakeClient(readback=[record.values()])
    assert ledger.append_once(client, record) is True
    assert len(client.appended) == 1
    assert client.appended[0][1] == record.values()
    assert "AutonomousDevelopment!A5:Q5" in client.read_ranges


def test_append_once_is_idempotent_only_for_matching_existing_row():
    record = make_record("123")
    client = FakeClient(existing=[record.values()])
    assert ledger.append_once(client, record) is False
    assert client.appended == []


def test_append_once_fails_closed_for_conflicting_existing_run_id():
    record = make_record("123")
    conflicting = record.values()
    conflicting[7] = "different-sha"
    client = FakeClient(existing=[conflicting])
    try:
        ledger.append_once(client, record)
    except RuntimeError as exc:
        assert "mismatched ledger data" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_unconfirmed_append():
    client = FakeClient(response={"updates": {"updatedRows": 0}})
    try:
        ledger.append_once(client, make_record("456"))
    except RuntimeError as exc:
        assert "updatedRows=0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_missing_updated_range():
    client = FakeClient(response={"updates": {"updatedRows": 1}})
    try:
        ledger.append_once(client, make_record("457"))
    except RuntimeError as exc:
        assert "updatedRange" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_readback_mismatch():
    record = make_record("458")
    wrong = record.values()
    wrong[12] = "PASS"
    client = FakeClient(readback=[wrong])
    try:
        ledger.append_once(client, record)
    except RuntimeError as exc:
        assert "read-back mismatch" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_record_autonomous_run_retries_once_after_constructor_failure(monkeypatch):
    calls = []

    class Factory:
        def __call__(self):
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("temporary Sheets failure")
            return FakeClient(readback=[make_record("789").values()])

    monkeypatch.setattr(ledger, "GoogleSheetsClient", Factory())
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    monkeypatch.setenv("AUTONOMOUS_TIMESTAMP", "2026-09-23T03:00:00Z")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "scheduled-distributed-development")
    monkeypatch.setenv("DEV_INSTRUCTION", "test")

    assert ledger.record_autonomous_run() is True
    assert calls == [0, 1]


def test_record_autonomous_run_deduplicates_after_append_then_client_error(monkeypatch):
    record = make_record("790")
    shared_rows = []

    class Client:
        def __init__(self, fail_after_append=False):
            self.fail_after_append = fail_after_append

        def read_rows(self, range_name):
            if range_name == "AutonomousDevelopment!A5:Q5" and shared_rows:
                return [shared_rows[0]]
            return [ledger.HEADERS]

        def update_row(self, *args):
            return {"updatedRows": 1}

        def search_column(self, *args):
            return [shared_rows[0]] if shared_rows else []

        def append_row(self, *args):
            shared_rows.append(record.values())
            if self.fail_after_append:
                raise RuntimeError("response lost after server-side append")
            return {
                "updates": {
                    "updatedRows": 1,
                    "updatedRange": "AutonomousDevelopment!A5:Q5",
                }
            }

    calls = []

    class Factory:
        def __call__(self):
            client = Client(fail_after_append=(len(calls) == 0))
            calls.append(client)
            return client

    monkeypatch.setattr(ledger, "GoogleSheetsClient", Factory())
    monkeypatch.setenv("GITHUB_RUN_ID", "790")
    monkeypatch.setenv("AUTONOMOUS_TIMESTAMP", record.timestamp)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", record.task_id)
    monkeypatch.setenv("DEV_INSTRUCTION", record.task_summary)

    assert ledger.record_autonomous_run() is False
    assert len(calls) == 2
    assert shared_rows == [record.values()]

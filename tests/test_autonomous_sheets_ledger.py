from agents.sheets.autonomous_ledger import AutonomousRunRecord, HEADERS, append_once


class FakeClient:
    def __init__(self, existing=None, response=None, readback=None):
        self.existing = existing or []
        self.response = response or {
            "updates": {"updatedRows": 1, "updatedRange": "AutonomousDevelopment!A5:Q5"}
        }
        self.readback = readback
        self.appended = []
        self.read_ranges = []
        self.updated = []

    def search_column(self, *args):
        return self.existing

    def append_row(self, *args):
        self.appended.append(args)
        return self.response

    def read_rows(self, range_name):
        self.read_ranges.append(range_name)
        if range_name == "AutonomousDevelopment!A5:Q5" and self.readback is not None:
            return self.readback
        return [HEADERS]

    def update_row(self, *args):
        self.updated.append(args)
        return {"updatedRows": 1}


def record(run_id="123"):
    return AutonomousRunRecord(
        "2026-09-22T00:00:00Z", run_id, "task", "scheduler", "ManagementAI",
        "test", "base", "head", "a.py", "https://example/pr/1",
        "PASS", "NOT_RUN", "PASS", "NOT_AUTO_MERGED", "", "review_pr"
    )


def test_append_once_writes_and_reads_back_exact_row():
    item = record()
    client = FakeClient(readback=[item.values()])
    assert append_once(client, item) is True
    assert client.appended[0][1] == item.values()
    assert "AutonomousDevelopment!A5:Q5" in client.read_ranges


def test_append_once_is_idempotent_for_matching_full_row():
    item = record()
    client = FakeClient(existing=[item.values()])
    assert append_once(client, item) is False
    assert client.appended == []


def test_append_once_fails_closed_for_conflicting_run_id():
    item = record()
    conflicting = item.values()
    conflicting[7] = "different-sha"
    try:
        append_once(FakeClient(existing=[conflicting]), item)
    except RuntimeError as exc:
        assert "mismatched ledger data" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_unconfirmed_append():
    try:
        append_once(FakeClient(response={"updates": {"updatedRows": 0}}), record("456"))
    except RuntimeError as exc:
        assert "updatedRows=0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_missing_updated_range():
    try:
        append_once(FakeClient(response={"updates": {"updatedRows": 1}}), record("457"))
    except RuntimeError as exc:
        assert "updatedRange" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_readback_mismatch():
    item = record("458")
    wrong = item.values()
    wrong[12] = "BLOCKED"
    try:
        append_once(FakeClient(readback=[wrong]), item)
    except RuntimeError as exc:
        assert "read-back mismatch" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_record_has_seventeen_columns():
    assert len(record().values()) == 17

import agents.sheets.autonomous_ledger as ledger

SHEET = "AutonomousDevelopment"

class FakeClient:
    def __init__(self, existing=None, response=None, readback=None):
        self.existing = existing or []
        self.response = response or {"updates": {"updatedRows": 1, "updatedRange": "AutonomousDevelopment!AE185:AU185"}}
        self.readback = readback
        self.appended = []
        self.read_ranges = []

    def append_row(self, *args):
        self.appended.append(args)
        return self.response

    def read_rows(self, range_name):
        self.read_ranges.append(range_name)
        if range_name == "AutonomousDevelopment!A:ZZ":
            return [[ ""] * 30 + ledger.HEADERS, *self.existing]
        if range_name == "AutonomousDevelopment!AE185:AU185" and self.readback is not None:
            return self.readback
        return []

    def update_row(self, *args):
        return {"updatedRows": 1}

def record(run_id="123"):
    return ledger.AutonomousRunRecord(
        "2026-09-22T00:00:00Z", run_id, "task", "scheduler", "ManagementAI",
        "test", "base", "head", "a.py", "https://example/pr/1",
        "PASS", "NOT_RUN", "PASS", "NOT_AUTO_MERGED", "", "review_pr"
    )

def test_append_once_accepts_existing_table_location():
    item = record()
    client = FakeClient(readback=[item.values()])
    assert ledger.append_once(client, item) is True
    assert client.appended[0][0] == "AutonomousDevelopment!A:ZZ"
    assert "AutonomousDevelopment!A:ZZ" in client.read_ranges

def test_append_once_is_idempotent_for_matching_full_row():
    item = record()
    client = FakeClient(existing=[[""] * 30 + item.values()])
    assert ledger.append_once(client, item) is False
    assert client.appended == []

def test_append_once_fails_closed_for_conflicting_run_id():
    item = record()
    conflicting = item.values()
    conflicting[7] = "different-sha"
    try:
        ledger.append_once(FakeClient(existing=[[""] * 30 + conflicting]), item)
    except RuntimeError as exc:
        assert "mismatched ledger data" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

def test_append_once_rejects_unconfirmed_append():
    try:
        ledger.append_once(FakeClient(response={"updates": {"updatedRows": 0}}), record("456"))
    except RuntimeError as exc:
        assert "updatedRows=0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

def test_append_once_rejects_wrong_width():
    item = record("459")
    client = FakeClient(response={"updates": {"updatedRows": 1, "updatedRange": "AutonomousDevelopment!AE185:AT185"}}, readback=[item.values()])
    try:
        ledger.append_once(client, item)
    except RuntimeError as exc:
        assert "column width" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

def test_append_once_rejects_readback_mismatch():
    item = record("458")
    wrong = item.values()
    wrong[12] = "BLOCKED"
    try:
        ledger.append_once(FakeClient(readback=[wrong]), item)
    except RuntimeError as exc:
        assert "read-back mismatch" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

def test_record_has_seventeen_columns():
    assert len(record().values()) == 17

from agents.sheets.autonomous_ledger import AutonomousRunRecord, append_once


class FakeClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.appended = []
        self.error = error

    def search(self, _range, keyword):
        if self.error:
            raise self.error
        return [row for row in self.rows if keyword in [str(cell) for cell in row]]

    def append_row(self, _range, values):
        if self.error:
            raise self.error
        self.appended.append(values)


def record():
    return AutonomousRunRecord(
        "2026-09-22T00:00:00Z", "123", "task", "scheduler", "ManagementAI",
        "test", "base", "head", "a.py", "https://example/pr/1",
        "PASS", "PASS", "PASS", "NOT_AUTO_MERGED", "", "review_pr"
    )


def test_append_once_writes_new_run():
    client = FakeClient()
    assert append_once(client, record()) is True
    assert len(client.appended) == 1


def test_append_once_is_idempotent():
    client = FakeClient([["2026-09-22", "123"]])
    assert append_once(client, record()) is False
    assert client.appended == []


def test_record_keeps_failure_fields():
    item = record()
    item = AutonomousRunRecord(
        **{**item.__dict__, "tests_result": "FAIL",
           "blocked_failed_reason": "pytest_failed"}
    )
    assert item.tests_result == "FAIL"
    assert item.blocked_failed_reason == "pytest_failed"


def test_append_once_propagates_api_failure():
    client = FakeClient(error=RuntimeError("Sheets API unavailable"))
    try:
        append_once(client, record())
    except RuntimeError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("API failure must not be swallowed")


def test_missing_configuration_is_rejected(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE", raising=False)
    from agents.sheets.client import GoogleSheetsClient
    try:
        GoogleSheetsClient()
    except ValueError as exc:
        assert "SPREADSHEET_ID" in str(exc)
    else:
        raise AssertionError("missing Sheets configuration must be rejected")

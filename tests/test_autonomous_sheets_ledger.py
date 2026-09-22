from agents.sheets.autonomous_ledger import AutonomousRunRecord, append_once


class FakeClient:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.appended = []
        self.error = error

    def search_column(self, _range, column_index, keyword):
        if self.error:
            raise self.error
        return [row for row in self.rows if len(row) > column_index and str(row[column_index]) == str(keyword)]

    def read_rows(self, range_name):
        if self.error:
            raise self.error
        if range_name.endswith("A1:Q1"):
            return [self.rows[0]] if self.rows and len(self.rows[0]) == 17 else []
        return self.rows

    def update_row(self, _range, values):
        if self.error:
            raise self.error
        self.rows = [values, *self.rows] if self.rows and len(self.rows[0]) != 17 else [values]

    def append_row(self, _range, values):
        if self.error:
            raise self.error
        self.appended.append(values)
        return {"updates": {"updatedRows": 1}}


def record():
    return AutonomousRunRecord(
        "2026-09-22T00:00:00Z", "123", "task", "scheduler", "ManagementAI",
        "test", "base", "head", "a.py", "https://example/pr/1",
        "PASS", "NOT_RUN", "PASS", "NOT_AUTO_MERGED", "", "review_pr"
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
    item = AutonomousRunRecord(**{**record().__dict__, "tests_result": "FAIL", "blocked_failed_reason": "pytest_failed"})
    assert item.tests_result == "FAIL"
    assert item.blocked_failed_reason == "pytest_failed"


def test_partial_run_id_does_not_match():
    client = FakeClient([["date", "12345"]])
    assert append_once(client, record()) is True


def test_headers_are_initialized():
    client = FakeClient()
    append_once(client, record())
    assert client.rows[0][0] == "timestamp"
    assert client.rows[0][16] == "logging_result"


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


def test_record_has_seventeen_columns():
    assert len(record().values()) == 17


def test_ledger_range_covers_all_columns():
    from agents.sheets import autonomous_ledger
    assert autonomous_ledger.LEDGER_RANGE.endswith("A:Q")
from agents.sheets.autonomous_ledger import AutonomousRunRecord, append_once

class FakeClient:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.appended = []

    def search(self, _range, keyword):
        return [row for row in self.rows if keyword in [str(cell) for cell in row]]

    def append_row(self, _range, values):
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
    item = AutonomousRunRecord(**{**item.__dict__, "tests_result": "FAIL",
                                  "blocked_failed_reason": "pytest_failed"})
    assert item.tests_result == "FAIL"
    assert item.blocked_failed_reason == "pytest_failed"

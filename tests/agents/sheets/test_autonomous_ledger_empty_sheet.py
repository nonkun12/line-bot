import pytest

from agents.sheets import autonomous_ledger as ledger


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.updated = []

    def read_rows(self, range_name):
        if range_name.endswith("!A1:Q1"):
            return [self.rows[0]] if self.rows else []
        return self.rows

    def update_row(self, range_name, values):
        self.updated.append((range_name, values))
        self.rows = [list(values)]


def test_empty_sheet_is_initialized_without_overwrite(monkeypatch):
    client = FakeClient([])
    monkeypatch.setattr(ledger, "LEDGER_RANGE", "AutonomousDevelopment!A:ZZ")
    assert ledger.ensure_headers(client) == "AutonomousDevelopment!A:ZZ"
    assert client.updated == [("AutonomousDevelopment!A1:Q1", ledger.HEADERS)]
    assert client.rows == [ledger.HEADERS]


def test_non_empty_sheet_without_headers_fails_closed(monkeypatch):
    client = FakeClient([["existing", "data"]])
    monkeypatch.setattr(ledger, "LEDGER_RANGE", "AutonomousDevelopment!A:ZZ")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        ledger.ensure_headers(client)


def test_existing_headers_are_reused(monkeypatch):
    client = FakeClient([ledger.HEADERS])
    monkeypatch.setattr(ledger, "LEDGER_RANGE", "AutonomousDevelopment!A:ZZ")
    assert ledger.ensure_headers(client) == "AutonomousDevelopment!A:ZZ"
    assert client.updated == []

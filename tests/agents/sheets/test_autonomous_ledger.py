from agents.sheets.autonomous_ledger import (
    HEADERS,
    AutonomousRunRecord,
    _discover_table_range,
    append_once,
    ensure_headers,
)


class FakeSheetsClient:
    def __init__(self, header_start=30):
        self.header_start = header_start
        self.updated = None
        self.appended = None

    def read_rows(self, range_name):
        if range_name == "AutonomousDevelopment!A:ZZ":
            row = [""] * self.header_start + HEADERS[:]
            return [row]
        if range_name == "AutonomousDevelopment!AE185:AU185":
            return [self.appended] if self.appended is not None else []
        return []

    def update_row(self, range_name, values):
        self.updated = (range_name, values)

    def search_column(self, range_name, column_index, keyword):
        return []

    def append_row(self, range_name, values):
        self.appended = list(values)
        return {
            "updates": {
                "updatedRows": 1,
                "updatedRange": "AutonomousDevelopment!AE185:AU185",
            }
        }


def _record():
    values = ["v1"] * len(HEADERS)
    return AutonomousRunRecord(*values)


def test_discover_existing_ledger_table_at_current_location(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_DEV_LEDGER_RANGE", "AutonomousDevelopment!U:AK")
    import agents.sheets.autonomous_ledger as ledger
    monkeypatch.setattr(ledger, "LEDGER_RANGE", "AutonomousDevelopment!U:AK")
    client = FakeSheetsClient()
    assert _discover_table_range(client) == "AutonomousDevelopment!AE:AU"


def test_append_uses_discovered_table_and_accepts_actual_row(monkeypatch):
    import agents.sheets.autonomous_ledger as ledger
    monkeypatch.setattr(ledger, "LEDGER_RANGE", "AutonomousDevelopment!U:AK")
    client = FakeSheetsClient()
    assert append_once(client, _record()) is True
    assert client.updated is None
    assert client.appended == ["v1"] * len(HEADERS)

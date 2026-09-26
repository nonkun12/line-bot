from types import SimpleNamespace
from core.google_sheets_writer import GoogleSheetsWriter

def test_from_environment_is_disabled_without_spreadsheet_id(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE", raising=False)
    assert GoogleSheetsWriter.from_environment() is None

def test_append_development_result_uses_single_audit_row():
    calls = []
    class Values:
        def append(self, **kwargs): calls.append(kwargs); return self
        def execute(self): return {"updates": {"updatedRows": 1}}
    service = SimpleNamespace(spreadsheets=lambda: SimpleNamespace(values=lambda: Values()))
    writer = GoogleSheetsWriter(service, "sheet-id", "DevelopmentAudit!A:I")
    writer.append_development_result(instruction="run autonomous development", status="BLOCKED", target_path="tests/test_example.py", branch="line-dev/123", detail="development branch pushed", base_sha="base", produced_sha="produced")
    assert len(calls) == 1
    assert calls[0]["spreadsheetId"] == "sheet-id"
    assert calls[0]["range"] == "DevelopmentAudit!A:I"
    assert calls[0]["valueInputOption"] == "RAW"
    assert calls[0]["insertDataOption"] == "INSERT_ROWS"
    assert calls[0]["body"]["values"][0][1:] == ["BLOCKED", "run autonomous development", "tests/test_example.py", "line-dev/123", "base", "produced", "development branch pushed", "BLOCKED"]

"""Optional Google Sheets audit writer for autonomous development results.

The integration uses the already-supported Google API dependencies in the
project. It is disabled by default and only appends when explicitly enabled.
Credentials are read from environment variables; no credential material is
written to the repository.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

class GoogleSheetsWriter:
    def __init__(self, service: Any, spreadsheet_id: str, range_name: str) -> None:
        self._service = service
        self._spreadsheet_id = spreadsheet_id
        self._range_name = range_name

    @classmethod
    def from_environment(cls) -> "GoogleSheetsWriter | None":
        spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
        if not spreadsheet_id:
            return None
        credentials_json = os.environ.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "").strip()
        credentials_file = os.environ.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE", "").strip()
        if not credentials_json and not credentials_file:
            return None
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        if credentials_json:
            credentials = service_account.Credentials.from_service_account_info(json.loads(credentials_json), scopes=SCOPES)
        else:
            credentials = service_account.Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        range_name = os.environ.get("GOOGLE_SHEETS_AUDIT_RANGE", "DevelopmentAudit!A:I").strip() or "DevelopmentAudit!A:I"
        return cls(service, spreadsheet_id, range_name)

    def append_development_result(self, *, instruction: str, status: str, target_path: str | None, branch: str | None, detail: str, base_sha: str | None, produced_sha: str | None) -> None:
        row = [datetime.now(timezone.utc).isoformat(), status[:40], instruction[:2000], target_path or "", branch or "", base_sha or "", produced_sha or "", detail[:4000], "PASS"]
        (self._service.spreadsheets().values().append(spreadsheetId=self._spreadsheet_id, range=self._range_name, valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [row]}).execute())

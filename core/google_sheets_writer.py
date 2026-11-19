"""Google Sheets audit writer for development and runtime results.

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
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(credentials_json), scopes=SCOPES
            )
        else:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file, scopes=SCOPES
            )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

        # The existing Sheets Agent addresses the configured spreadsheet by
        # column-only ranges (A:A / A:Z), which target the spreadsheet's first
        # sheet. Keep the audit writer consistent instead of assuming a tab
        # named "DevelopmentAudit". A named range can still be supplied when a
        # dedicated audit tab is intentionally configured.
        range_name = (
            os.environ.get("GOOGLE_SHEETS_AUDIT_RANGE", "A:I").strip()
            or "A:I"
        )
        return cls(service, spreadsheet_id, range_name)

    def append_development_result(
        self,
        *,
        instruction: str,
        status: str,
        target_path: str | None,
        branch: str | None,
        detail: str,
        base_sha: str | None,
        produced_sha: str | None,
    ) -> None:
        row = [
            datetime.now(timezone.utc).isoformat(),
            status[:40],
            instruction[:2000],
            target_path or "",
            branch or "",
            base_sha or "",
            produced_sha or "",
            detail[:4000],
            status[:40],
        ]
        response = (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=self._range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )
        updated_rows = response.get("updates", {}).get("updatedRows")
        if updated_rows != 1:
            raise RuntimeError(
                f"Google Sheets audit append did not update exactly one row: {response!r}"
            )

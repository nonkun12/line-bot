"""Guarded, on-demand Google Sheets append support.

No automatic synchronization policy is implemented here. Callers must explicitly
set write_requested=True before any write is attempted.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Iterable, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class GoogleSheetsConfigurationError(RuntimeError):
    """Raised when Sheets integration is not configured safely."""


class GoogleSheetsWriteDenied(PermissionError):
    """Raised when a caller did not explicitly request a Sheets write."""


def _credentials():
    encoded = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON_B64", "").strip()
    if encoded:
        try:
            payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleSheetsConfigurationError(
                "GOOGLE_SHEETS_CREDENTIALS_JSON_B64 is invalid"
            ) from exc
        return service_account.Credentials.from_service_account_info(
            payload, scopes=SCOPES
        )

    credentials_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if credentials_file:
        return service_account.Credentials.from_service_account_file(
            credentials_file, scopes=SCOPES
        )

    raise GoogleSheetsConfigurationError(
        "Google Sheets credentials are not configured"
    )


def append_rows(
    rows: Iterable[Sequence[object]],
    *,
    write_requested: bool,
    spreadsheet_id: str | None = None,
    worksheet_range: str | None = None,
) -> dict:
    """Append rows only when the caller explicitly requested a write."""
    if not write_requested:
        raise GoogleSheetsWriteDenied(
            "Google Sheets write requires an explicit write request"
        )

    resolved_spreadsheet_id = (
        spreadsheet_id or os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    )
    resolved_range = (
        worksheet_range
        or os.getenv("GOOGLE_SHEETS_WORKSHEET_RANGE", "Sheet1!A:Z").strip()
    )
    if not resolved_spreadsheet_id:
        raise GoogleSheetsConfigurationError(
            "GOOGLE_SHEETS_SPREADSHEET_ID is not configured"
        )

    materialized_rows = [list(row) for row in rows]
    if not materialized_rows:
        raise ValueError("At least one row is required")

    service = build(
        "sheets", "v4", credentials=_credentials(), cache_discovery=False
    )
    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=resolved_spreadsheet_id,
            range=resolved_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"majorDimension": "ROWS", "values": materialized_rows},
        )
        .execute()
    )
    return response.get("updates", {})

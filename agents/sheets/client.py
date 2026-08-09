"""
Google Sheets API client.
"""

import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


class GoogleSheetsClient:

    def __init__(self, spreadsheet_id: str | None = None):
        self.spreadsheet_id = (
            spreadsheet_id
            or os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        )

        credentials_json = os.getenv(
            "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"
        )

        credentials_file = os.getenv(
            "GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE"
        )

        if not self.spreadsheet_id:
            raise ValueError(
                "GOOGLE_SHEETS_SPREADSHEET_ID is not configured."
            )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets"
        ]

        if credentials_json:
            import json

            credentials_info = json.loads(credentials_json)

            print(
                "SHEETS DEBUG: spreadsheet_id_length=",
                len(self.spreadsheet_id),
            )
            print(
                "SHEETS DEBUG: client_email=",
                credentials_info.get("client_email"),
            )
            print(
                "SHEETS DEBUG: credential_type=",
                credentials_info.get("type"),
            )

            credentials = Credentials.from_service_account_info(
                credentials_info,
                scopes=scopes,
            )

        elif credentials_file:
            credentials = Credentials.from_service_account_file(
                credentials_file,
                scopes=scopes,
            )

        else:
            raise ValueError(
                "Google Sheets service account credentials are not configured."
            )

        self.service = build(
            "sheets",
            "v4",
            credentials=credentials,
        )

    def read_rows(self, range_name: str):
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        return result.get("values", [])

    def append_row(self, range_name: str, values: list):
        result = (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            )
            .execute()
        )

        return result

    def search(self, range_name: str, keyword: str):
        rows = self.read_rows(range_name)

        return [
            row
            for row in rows
            if any(
                keyword in str(cell)
                for cell in row
            )
        ]

#!/usr/bin/env python3
"""
Google Sheets API connection diagnostic script.
Performs read-only connection check.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to sys.path to allow importing 'agents'
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv

# Import Google OAuth and Sheets libraries
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from agents.sheets.client import GoogleSheetsClient


def run_verification() -> bool:
    """
    Performs read-only verification steps for Google Sheets connection.
    Returns True if all verification steps pass, False otherwise.
    """
    # Load environment variables
    load_dotenv()

    success = True

    # 1. Check GOOGLE_SHEETS_SPREADSHEET_ID existence
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if spreadsheet_id and spreadsheet_id.strip():
        print("① SPREADSHEET_ID check: ✅ OK")
    else:
        print("① SPREADSHEET_ID check: ❌ NG (GOOGLE_SHEETS_SPREADSHEET_ID is missing or empty)")
        success = False

    # 2. Check credentials variables
    creds_json = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    creds_file = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE")

    if creds_json and creds_json.strip():
        print("② Credentials env check: ✅ OK (Using GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON)")
    elif creds_file and creds_file.strip():
        print("② Credentials env check: ✅ OK (Using GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE)")
    else:
        print("② Credentials env check: ❌ NG (Neither GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON nor GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE is set)")
        success = False

    # Fail early if spreadsheet ID or credentials config is missing
    if not success:
        return False

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = None

    # 3. Check if credentials can be built (Google service account)
    try:
        if creds_json:
            creds_info = json.loads(creds_json)
            if not isinstance(creds_info, dict):
                raise ValueError("Credentials JSON must be a dictionary object")

            # Check for required service account keys without printing them
            required_keys = ["type", "project_id", "private_key_id", "private_key", "client_email"]
            missing_keys = [k for k in required_keys if k not in creds_info]
            if missing_keys:
                raise ValueError(f"Missing required keys in service account JSON: {missing_keys}")

            credentials = Credentials.from_service_account_info(
                creds_info,
                scopes=scopes
            )
        else:
            if not os.path.exists(creds_file):
                raise FileNotFoundError(f"Credentials file does not exist at: {creds_file}")
            credentials = Credentials.from_service_account_file(
                creds_file,
                scopes=scopes
            )
        print("③ Google Credentials build: ✅ OK")
    except Exception:
        print("③ Google Credentials build: ❌ NG (Google credentials build failed)")
        return False

    # 4. Check if GoogleSheetsClient can be instantiated
    client = None
    try:
        client = GoogleSheetsClient()
        print("④ GoogleSheetsClient instantiation: ✅ OK")
    except Exception:
        print("④ GoogleSheetsClient instantiation: ❌ NG (GoogleSheetsClient instantiation failed)")
        return False

    # 5. Check read-only spreadsheet API access (metadata fetch)
    try:
        # Call client's underlying sheets service directly to read metadata
        # which is 100% read-only and does not modify the sheet.
        # It also doesn't depend on target sheet's layout or name, just checks if ID exists and is accessible.
        spreadsheet = (
            client.service.spreadsheets()
            .get(spreadsheetId=client.spreadsheet_id)
            .execute()
        )
        title = spreadsheet.get("properties", {}).get("title", "Unknown")
        sheets_count = len(spreadsheet.get("sheets", []))
        print(f"⑤ Read-only API access check: ✅ OK (Successfully connected. Spreadsheet Title: '{title}', Sheets Count: {sheets_count})")
    except Exception:
        print("⑤ Read-only API access check: ❌ NG (Google Sheets API access failed)")
        return False

    return True


def main():
    success = run_verification()
    if success:
        print("\nConnection verification: ✅ OK")
        sys.exit(0)
    else:
        print("\nConnection verification: ❌ NG")
        sys.exit(1)


if __name__ == "__main__":
    main()

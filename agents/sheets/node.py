"""
Google Sheets Agent LangGraph node
"""

import os

from agents.sheets.client import GoogleSheetsClient
from agents.sheets.handlers import handle_sheets_message


def sheets_agent_node(state):
    message = state.get("raw_message", "")
    user_id = state.get("user_id", "")

    client = GoogleSheetsClient(
        spreadsheet_id=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    )

    result = handle_sheets_message(
        message,
        user_id,
        client,
    )

    if result is None:
        result = {
            "text": "Google Sheetsの操作を理解できませんでした。",
            "success": False,
        }

    results = dict(
        state.get("agent_results", {})
    )

    results["sheets"] = result

    return {
        **state,
        "agent_results": results,
    }

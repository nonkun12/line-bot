"""
Google Sheets Agent schemas
"""

from typing import TypedDict


class SheetsResult(TypedDict, total=False):
    text: str
    rows: list
    success: bool

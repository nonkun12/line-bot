"""Small persistence wrapper for per-user stock watchlists."""
from __future__ import annotations

import db

from core.stocks import normalize_stock_ticker


def add(user_id: str, ticker: str, label: str = "") -> bool:
    return db.add_stock_watch(user_id, normalize_stock_ticker(ticker), label.strip())


def remove(user_id: str, ticker: str) -> bool:
    return db.remove_stock_watch(user_id, normalize_stock_ticker(ticker))


def list_all(user_id: str) -> list[dict]:
    return db.list_stock_watches(user_id)

import re
from unittest.mock import patch

from app import _build_dashboard_url, generate_reply


def test_build_stock_dashboard_url_uses_signed_stock_path(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    with patch("app.time.time", return_value=1790119800):
        url = _build_dashboard_url("U-test", "/stock-dashboard")

    assert url.startswith("https://line-bot-yvea.onrender.com/stock-dashboard?")
    assert "user_id=U-test" in url
    assert "ts=1790119800" in url
    assert re.search(r"token=[0-9a-f]{64}", url)


def test_generate_reply_stock_dashboard_command(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    with patch("app.time.time", return_value=1790119800):
        reply = generate_reply("U-test", "株式ダッシュボード")

    assert reply.startswith("株式投資ダッシュボードはこちらです。\n")
    assert "/stock-dashboard?" in reply


def test_generate_reply_existing_dashboard_command_is_unchanged(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    with patch("app.time.time", return_value=1790119800):
        reply = generate_reply("U-test", "ダッシュボード")

    assert reply.startswith("ダッシュボードはこちらです。\n")
    assert "https://line-bot-yvea.onrender.com/dashboard?" in reply

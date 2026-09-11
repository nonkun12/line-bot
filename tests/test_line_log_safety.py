from __future__ import annotations

from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_callback_does_not_log_raw_line_body_or_signature() -> None:
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'print("BODY:", body)' not in source
    assert 'print("SIGNATURE:", signature)' not in source
    assert 'print("BODY LENGTH:", len(body))' in source

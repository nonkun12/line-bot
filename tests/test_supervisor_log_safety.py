from pathlib import Path


SUPERVISOR_SOURCE = Path(__file__).resolve().parents[1] / "graph" / "supervisor.py"


def test_supervisor_does_not_log_raw_user_input():
    source = SUPERVISOR_SOURCE.read_text(encoding="utf-8")

    assert 'print("RAW:", text)' not in source
    assert 'print("===== SUPERVISOR =====")' in source

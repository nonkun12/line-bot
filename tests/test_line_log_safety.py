from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_callback_does_not_log_raw_line_payload_or_signature():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'print("BODY:", body)' not in source
    assert 'print("SIGNATURE:", signature)' not in source
    assert 'print("BODY LENGTH:", len(body))' in source
    assert 'print("SIGNATURE PRESENT:", bool(signature))' in source


def test_application_does_not_enable_dependency_debug_logging():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "logging.basicConfig(level=logging.DEBUG)" not in source
    assert "logging.basicConfig(level=logging.INFO)" in source


def test_environment_specific_secret_files_are_ignored():
    ignore = (APP_SOURCE.parent / ".gitignore").read_text(encoding="utf-8")

    assert ".env.*" in ignore
    assert "!.env.example" in ignore

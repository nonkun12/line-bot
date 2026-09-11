from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_legacy_generate_reply_does_not_log_raw_message_or_result():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'print("=== GENERATE_REPLY ===", repr(message))' not in source
    assert 'print("MESSAGE DEBUG:", repr(message), type(message))' not in source
    assert "traceback.print_exc()" not in source
    assert "print(result)" not in source
    assert 'print("=== GENERATE_REPLY: received ===")' in source
    assert 'print("===== AFTER GRAPH.INVOKE: completed =====")' in source


def test_callback_and_process_logs_do_not_include_raw_exception_or_user_id():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'print(exc)' not in source
    assert 'print("[LOG] Core gateway failed; returning safe reply:", exc)' not in source
    assert 'print("[LOG] LINE reply failed; falling back to push:", exc)' not in source
    assert 'print(f"[LOG] _process_and_reply called: user_id={user_id}")' not in source
    assert 'print(f"[LOG] USER LOCK ACQUIRED: {user_id}")' not in source

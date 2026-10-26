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


def test_ai_report_workflow_does_not_echo_or_inline_interpolate_secrets():
    workflow = (
        APP_SOURCE.parent / ".github" / "workflows" / "ai-report.yml"
    ).read_text(encoding="utf-8")

    assert 'echo "${{ secrets.AI_REPORT_URL }}"' not in workflow
    assert 'x-internal-key: ${{ secrets.INTERNAL_PUSH_KEY }}' not in workflow
    assert "permissions: {}" in workflow
    assert 'AI_REPORT_URL: ${{ secrets.AI_REPORT_URL }}' in workflow


def test_workflow_run_debugger_does_not_checkout_untrusted_commit():
    workflow = (
        APP_SOURCE.parent / ".github" / "workflows" / "ai-debug-agent.yml"
    ).read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" not in workflow


def test_ci_debug_summary_does_not_publish_raw_pytest_log():
    analyzer = (
        APP_SOURCE.parent / "scripts" / "ci_debug_trigger.py"
    ).read_text(encoding="utf-8")

    assert "lines.append(full_log)" not in analyzer
    assert "Raw pytest log omitted for privacy" in analyzer


def test_external_service_errors_do_not_echo_raw_exception_details():
    root = APP_SOURCE.parent
    delegate = (root / "n8n_delegate.py").read_text(encoding="utf-8")
    wikipedia = (root / "wikipedia_tool.py").read_text(encoding="utf-8")

    assert "error=str(exc)" not in delegate
    assert 'print("N8N DELEGATE ERROR:", exc)' not in delegate
    assert 'print("[WIKIPEDIA ERROR] summary lookup failed:", exc)' not in wikipedia

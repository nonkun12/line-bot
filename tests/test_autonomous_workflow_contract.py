from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nightly-autonomous-worker.yml"

def test_autonomous_workflow_keeps_jst_schedule_slots():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cron: '5 3 * * *'" in text
    assert "cron: '5 15 * * *'" in text
    assert "cron: '5 21 * * *'" in text
    assert "timezone: 'Asia/Tokyo'" in text

def test_autonomous_workflow_does_not_escape_github_or_shell_variables():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\\${{" not in text
    assert "\\${AUTONOMOUS_" not in text
    assert "GOOGLE_SHEETS_SPREADSHEET_ID: ${{ secrets.GOOGLE_SHEETS_SPREADSHEET_ID }}" in text
    assert "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}" in text
    assert 'export AUTONOMOUS_SAFETY_GATE_RESULT="${AUTONOMOUS_SAFETY_GATE_RESULT:-BLOCKED}"' in text

def test_autonomous_workflow_preserves_fail_tolerant_audit():
    text = WORKFLOW.read_text(encoding="utf-8")
    audit_start = text.index("- name: Record autonomous development result to Google Sheets")
    audit_end = text.index("- name: Notify Slack and LINE", audit_start)
    audit = text[audit_start:audit_end]
    assert "if: always()" in audit
    assert "continue-on-error: true" in audit
    assert "set +e" in audit

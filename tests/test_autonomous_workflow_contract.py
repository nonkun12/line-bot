from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "overnight-development.yml"

def test_autonomous_workflow_keeps_jst_schedule_slots():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "5 3 * * *"' in text
    assert 'cron: "5 15 * * *"' in text
    assert 'cron: "5 21 * * *"' in text
    assert 'timezone: "Asia/Tokyo"' in text

def test_autonomous_workflow_does_not_escape_github_or_shell_variables():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\\${{" not in text
    assert "\\${AUTONOMOUS_" not in text
    assert "GOOGLE_SHEETS_SPREADSHEET_ID: ${{ secrets.GOOGLE_SHEETS_SPREADSHEET_ID }}" in text
    assert "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}" in text
    assert 'export AUTONOMOUS_SAFETY_GATE_RESULT="${AUTONOMOUS_SAFETY_GATE_RESULT:-BLOCKED}"' in text
    assert 'SHEETS_LOGGING_RESULT: ${{ env.AUTONOMOUS_LOGGING_RESULT }}' in text

def test_autonomous_workflow_preserves_fail_tolerant_audit():
    text = WORKFLOW.read_text(encoding="utf-8")
    audit_start = text.index("- name: Record autonomous development result to Google Sheets")
    audit_end = text.index("- name: Notify Slack", audit_start)
    audit = text[audit_start:audit_end]
    assert "if: always()" in audit
    assert "continue-on-error: true" in audit
    assert "set +e" in audit


def test_autonomous_workflow_blocks_existing_branch_but_allows_new_branch():
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = text[text.index("- name: Create GitHub PR"):text.index("- name: Record autonomous development result to Google Sheets")]
    assert 'if git ls-remote --exit-code origin "refs/heads/${BRANCH}" >/dev/null 2>&1; then' in guard
    assert 'echo "Autonomous branch already exists: ${BRANCH}"' in guard
    assert 'exit 1' in guard


def test_legacy_nightly_workflow_has_no_automatic_schedule():
    legacy = ROOT / ".github" / "workflows" / "nightly-autonomous-worker.yml"
    text = legacy.read_text(encoding="utf-8")
    schedule_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" not in schedule_block


def test_autonomous_workflow_has_final_safety_gate_before_pr_creation():
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text[text.index("- name: Validate autonomous result and Safety Gate"):text.index("- name: Create GitHub PR")]
    assert "git diff --check" in gate
    assert "AUTONOMOUS_SAFETY_GATE_RESULT=PASS" in gate
    assert "AUTONOMOUS_SUMMARY_PATH" in gate


def test_autonomous_workflow_does_not_hardcode_one_development_target():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "tests/test_management_router.py に固定" not in text
    assert "安全な候補から現在のコードとテストに基づいて改善対象を1ファイルだけ選び" in text

def test_autonomous_workflow_persists_self_improvement_history_between_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Find previous successful autonomous run" in text
    assert "gh run list --workflow overnight-development.yml --branch main --status success --limit 1" in text
    assert "--json databaseId" in text
    assert "--jq" in text
    assert "Restore previous self-improvement history" in text
    assert "uses: actions/download-artifact@v4" in text
    assert "run-id:" in text
    assert "SELF_IMPROVEMENT_HISTORY_PATH:" in text
    assert "self-improvement-state/self-improvement.jsonl" in text
    assert "Persist self-improvement history" in text
    assert "uses: actions/upload-artifact@v4" in text
    assert "name: autonomous-self-improvement-state" in text
    assert "if: always()" in text
    restore = text[text.index("Restore previous self-improvement history"):text.index("Record autonomous starting commit")]
    assert "workflow: overnight-development.yml" not in restore
    assert "branch: main" not in restore

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "overnight-development.yml"

def test_autonomous_workflow_keeps_jst_schedule_slots():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "5 3 * * *"' in text
    assert 'cron: "5 15 * * *"' in text
    assert 'cron: "5 21 * * *"' in text
    assert 'timezone: "Asia/Tokyo"' in text


def test_distributed_loop_and_watchdog_schedules_are_aligned():
    distributed = (ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    watchdog = (ROOT / ".github" / "workflows" / "autonomous-development-watchdog.yml").read_text(encoding="utf-8")
    assert "cron: '30 4,10,16,22 * * *'" in distributed
    assert distributed.count("timezone: 'Asia/Tokyo'") == 1
    for hour in (5, 11, 17, 23):
        assert f"cron: '30 {hour} * * *'" in watchdog
    assert watchdog.count("timezone: 'Asia/Tokyo'") == 4
    assert "AUTONOMOUS_DEV_LEDGER_RANGE: ${{ secrets.AUTONOMOUS_DEV_LEDGER_RANGE || secrets.GOOGLE_SHEETS_AUDIT_RANGE || 'AutonomousDevelopment!A:ZZ' }}" in watchdog
    assert "INTERNAL_PUSH_KEY: ${{ secrets.INTERNAL_PUSH_KEY }}" in watchdog
    assert "DISTRIBUTED_LOOP_LINE_USER_ID: ${{ secrets.DISTRIBUTED_LOOP_LINE_USER_ID }}" in watchdog
    assert "send_internal_line_push(message)" in watchdog


def test_distributed_loop_reports_queue_exhaustion_as_no_tasks():
    distributed = (ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "status == 'NO_TASKS'" in distributed
    assert "result=\"NO_TASKS\"" in distributed
    assert "queue_exhausted_no_tasks" in distributed
    assert "task_id = task_id or 'distributed-loop-no-task-result'" not in distributed
    assert "_resolved_sheet(client)" in distributed
    assert "ensure_headers(client, tab)" in distributed
    assert "Queue exhausted; durable task state unchanged." in distributed
    assert "Queue exhausted; no task was executed." in distributed

def test_autonomous_workflow_does_not_escape_github_or_shell_variables():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\\${{" not in text
    assert "\\${AUTONOMOUS_" not in text
    assert "GOOGLE_SHEETS_SPREADSHEET_ID: ${{ secrets.GOOGLE_SHEETS_SPREADSHEET_ID }}" in text
    assert 'if [ -z "${GOOGLE_SHEETS_SPREADSHEET_ID:-}" ]; then' in text
    assert 'if [ -z "${GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON:-}" ]; then' in text
    assert '\\${GOOGLE_SHEETS_SPREADSHEET_ID' not in text
    assert '\\${GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON' not in text
    assert "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}" in text
    assert 'export AUTONOMOUS_SAFETY_GATE_RESULT="${AUTONOMOUS_SAFETY_GATE_RESULT:-BLOCKED}"' in text
    assert 'SHEETS_LOGGING_RESULT: ${{ env.AUTONOMOUS_LOGGING_RESULT }}' in text

def test_autonomous_workflow_surfaces_google_sheets_failures():
    text = WORKFLOW.read_text(encoding="utf-8")
    audit_start = text.index("- name: Record autonomous development result to Google Sheets")
    audit_end = text.index("- name: Notify Slack", audit_start)
    audit = text[audit_start:audit_end]
    assert "if: always()" in audit
    assert "continue-on-error: true" not in audit
    assert "set -euo pipefail" in audit
    assert "Google Sheets logging verification failed" in audit


def test_autonomous_workflow_pins_hermes_release_installer():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "345cd2b057a452236de401d3534b8502a7465e8d/scripts/install.sh" in text
    assert "--commit 345cd2b057a452236de401d3534b8502a7465e8d" in text
    assert "--skip-computer-use" in text

def test_autonomous_workflow_reuses_the_worker_pushed_branch_for_pr_creation():
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = text[text.index("- name: Create GitHub PR"):text.index("- name: Persist self-improvement history")]
    assert "gh pr list" in guard
    assert '--head "${BRANCH}"' in guard
    assert "--base main" in guard
    assert 'if [ -z "$PR_URL" ]; then' in guard
    assert "gh pr create" in guard
    assert 'Autonomous PR already exists: ${PR_URL}' in guard
    assert 'git ls-remote --exit-code origin "refs/heads/${BRANCH}"' not in guard


def test_nightly_autonomous_worker_has_automatic_schedule():
    worker = ROOT / ".github" / "workflows" / "nightly-autonomous-worker.yml"
    text = worker.read_text(encoding="utf-8")
    schedule_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "schedule:" in schedule_block
    assert "cron: '0 4 * * *'" in schedule_block
    assert "cron: '0 16 * * *'" in schedule_block
    assert "cron: '0 22 * * *'" in schedule_block
    assert "timezone: 'Asia/Tokyo'" in schedule_block


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
    assert "Find previous completed autonomous run" in text
    assert "Verify autonomous ledger configuration" in text
    assert "missing GOOGLE_SHEETS_SPREADSHEET_ID" in text
    assert "missing GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON" in text
    assert "gh run list --workflow overnight-development.yml --branch main --status completed --limit 20" in text
    assert "--json databaseId,conclusion" in text
    assert 'select(.conclusion != "skipped")' in text
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


def test_autonomous_workflow_supports_explicit_on_demand_push_trigger():
    text = WORKFLOW.read_text(encoding="utf-8")
    event_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "push:" in event_block
    assert "branches:" in event_block
    assert "- main" in event_block
    assert "schedule:" in event_block
    assert "workflow_dispatch:" in event_block
    assert "[run-autonomous-loop]" in text
    assert "github.event_name != 'push'" in text

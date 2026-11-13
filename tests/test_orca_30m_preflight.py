from scripts.orca_30m_preflight import inspect_prerequisites


def test_missing_trusted_gate_configuration_fails_closed():
    result = inspect_prerequisites(env={})
    assert result["status"] == "BLOCKED"
    assert result["execution_enabled"] is False
    assert result["reason"].startswith("missing_trusted_gate_configuration:")


def test_execution_is_never_enabled_by_preflight_even_with_gate_pass(monkeypatch):
    import scripts.orca_30m_preflight as preflight

    class Snapshot:
        state = {
            "emergency_stop": False,
            "global_hold": False,
            "active_lease": None,
            "tasks": [{"task_id": "task-1", "request_hash": "a" * 64,
                       "status": "queued", "created_at": "2026-11-13T00:00:00Z"}],
            "consumed_approval_ids": [],
        }

    class Store:
        def read(self):
            return Snapshot()

    monkeypatch.setattr(
        preflight, "_json_env",
        lambda name: {"approval": {}, "budget": {}, "cycle": {}}.get(name, {}),
    )
    monkeypatch.setattr(
        "scripts.orca_github_execution_gate.evaluate_execution_gate",
        lambda **kwargs: {"status": "PASS", "execution_enabled": False},
    )
    env = {
        "ORCA_APPROVAL_JSON": "{}",
        "ORCA_APPROVAL_SIGNING_KEY": "x" * 32,
        "ORCA_ALLOWED_APPROVERS": "human",
        "ORCA_BUDGET_EVIDENCE_JSON": "{}",
        "ORCA_BUDGET_SIGNING_KEY": "y" * 32,
        "ORCA_BILLING_ACCOUNT_ID": "billing-account",
        "ORCA_IMPROVEMENT_CYCLE_JSON": "{}",
        "GITHUB_REPOSITORY": "nonkun12/line-bot",
    }
    result = inspect_prerequisites(env=env, store=Store())
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "phase3_worker_runtime_not_integrated"
    assert result["execution_enabled"] is False

def test_stale_scheduled_run_is_discarded():
    from datetime import datetime, timedelta, timezone
    from scripts.orca_30m_preflight import scheduled_run_is_fresh

    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    assert scheduled_run_is_fresh("2026-11-13T11:50:00Z", now=now) is True
    assert scheduled_run_is_fresh("2026-11-13T11:40:00Z", now=now) is False
    assert scheduled_run_is_fresh("invalid", now=now) is False

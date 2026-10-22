from pathlib import Path

from core.self_improvement import ImprovementSignal
from core.self_improvement_history import SelfImprovementHistory


def test_history_round_trips_and_is_bounded(tmp_path):
    store = SelfImprovementHistory(tmp_path / "history.jsonl", max_records=2)
    store.append(
        [
            ImprovementSignal("failure", "a", "first"),
            ImprovementSignal("repair", "a", "second"),
            ImprovementSignal("failure", "b", "third"),
        ]
    )

    assert store.load() == (
        ImprovementSignal("repair", "a", "development required repair attempts"),
        ImprovementSignal("failure", "b", "development failure observed"),
    )


def test_history_ignores_malformed_records(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(
        '{"kind":"failure","task_id":"ok","detail":"valid"}\n'
        'not-json\n'
        '{"kind":"failure","detail":}\n'
        '{"kind":"failure","task_id":"bad"}\n',
        encoding="utf-8",
    )
    store = SelfImprovementHistory(path)

    assert store.load() == (
        ImprovementSignal("failure", "ok", "valid"),
    )


def test_history_rejects_invalid_signal(tmp_path):
    store = SelfImprovementHistory(tmp_path / "history.jsonl")
    try:
        store.append([object()])
    except TypeError as exc:
        assert str(exc) == "history entries must be ImprovementSignal"
    else:
        raise AssertionError("expected TypeError")


def test_unreadable_history_fails_closed_without_overwriting(monkeypatch, tmp_path):
    path = tmp_path / "history.jsonl"
    original = '{"kind":"failure","task_id":"keep","detail":"preserve me"}\n'
    path.write_text(original, encoding="utf-8")
    store = SelfImprovementHistory(path)
    original_read_text = Path.read_text

    def fail_read_for_history(self, *args, **kwargs):
        if self == path:
            raise PermissionError("simulated unreadable history")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_for_history)

    try:
        store.append([ImprovementSignal("repair", "new", "must not erase old history")])
    except PermissionError as exc:
        assert "simulated unreadable history" in str(exc)
    else:
        raise AssertionError("expected unreadable history to fail closed")

    # Verify through the saved original reader: no destructive rewrite occurred.
    assert original_read_text(path, encoding="utf-8") == original



def test_history_redacts_signal_details_before_persisting(tmp_path):
    import json

    path = tmp_path / "history.jsonl"
    secret = "token=sk-example-secret"
    store = SelfImprovementHistory(path)
    store.append([ImprovementSignal("failure", "task-1", secret)])

    persisted = path.read_text(encoding="utf-8")
    assert secret not in persisted
    assert "sk-example-secret" not in persisted
    assert json.loads(persisted)["detail"] == "development failure observed"


def test_history_redacts_legacy_records_and_cycle_memory_on_next_write(tmp_path):
    import json

    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps({
            "kind": "failure",
            "task_id": "task-1",
            "detail": "legacy token=sk-legacy-secret",
        }) + "\n" + json.dumps({
            "record_type": "cycle_memory",
            "outcome": "FAIL",
            "cause": "private exception token=sk-memory-secret",
            "improvements": ["raw prompt sk-prompt-secret"],
            "next_action": "raw next action sk-action-secret",
            "target_path": "../private/path",
            "recurring_patterns": ["ValueError: sk-pattern-secret"],
        }) + "\n",
        encoding="utf-8",
    )
    store = SelfImprovementHistory(path)
    store.append([ImprovementSignal("repair", "task-2", "safe-looking detail")])

    persisted = path.read_text(encoding="utf-8")
    for secret in ("sk-legacy-secret", "sk-memory-secret", "sk-prompt-secret", "sk-action-secret", "sk-pattern-secret"):
        assert secret not in persisted
    rows = [json.loads(line) for line in persisted.splitlines()]
    assert rows[0]["detail"] == "development failure observed"
    assert rows[1]["cause"] == "development gate failed"
    assert rows[1]["target_path"] == ""
    assert rows[1]["recurring_patterns"] == []
    assert rows[2]["detail"] == "development required repair attempts"

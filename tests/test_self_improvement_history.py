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
        ImprovementSignal("repair", "a", "second"),
        ImprovementSignal("failure", "b", "third"),
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

## Backlog coverage tests

def test_cycle_memory_append_and_load_round_trip_without_mixing_signal_records(tmp_path):
    from core.self_improvement_history import SelfImprovementMemoryRecord
    store = SelfImprovementHistory(tmp_path / "history.jsonl")
    memory = SelfImprovementMemoryRecord(
        outcome="BLOCKED",
        cause="required evidence missing",
        improvements=("collect independent test evidence",),
        next_action="review evidence contract",
        target_path="tests/test_example.py",
        recurring_patterns=("missing_task_evidence",),
    )
    store.append_memory(memory)
    store.append([ImprovementSignal("failure", "task-1", "separate signal")])
    assert store.load_memory() == (memory,)
    assert store.load() == (ImprovementSignal("failure", "task-1", "separate signal"),)


def test_cycle_memory_load_rejects_invalid_limits_and_ignores_malformed_records(tmp_path):
    import pytest
    path = tmp_path / "history.jsonl"
    path.write_text(
        '{"record_type":"cycle_memory","outcome":"PASS","cause":"ok","improvements":[],"next_action":"continue"}\n'
        '{"record_type":"cycle_memory","outcome":"UNKNOWN","cause":"bad","improvements":[],"next_action":"stop"}\n',
        encoding="utf-8",
    )
    store = SelfImprovementHistory(path)
    assert len(store.load_memory()) == 1
    with pytest.raises(ValueError, match="limit must be between 1 and 20"):
        store.load_memory(limit=0)

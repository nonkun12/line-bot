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

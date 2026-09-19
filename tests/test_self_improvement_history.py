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

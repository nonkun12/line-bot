import json

from core.agent_runtime import RuntimeReport
from core.self_improvement_history import SelfImprovementHistory, SelfImprovementMemoryRecord
from core.self_improvement_cycle import run_self_improvement_cycle
from scripts.run_guarded_runtime import _augment_instruction_with_history


def test_cycle_memory_persists_outcome_cause_improvement_and_next_action(tmp_path):
    path = tmp_path / "memory.jsonl"
    report = RuntimeReport(
        completed=(),
        failed_task_id="tester",
        error="pytest gate failed: example failure",
        rounds=2,
        repair_attempts=1,
        integration_ready=False,
    )

    result = run_self_improvement_cycle(report, path, target_paths=("tests/example.py",))

    memories = SelfImprovementHistory(path).load_memory()
    assert len(memories) == 1
    memory = memories[0]
    assert memory.outcome == "FAIL"
    assert "pytest gate failed" in memory.cause
    assert memory.improvements
    assert "review" in memory.next_action
    assert memory.target_path == "tests/example.py"


def test_cycle_memory_is_ignored_by_signal_loader(tmp_path):
    path = tmp_path / "memory.jsonl"
    history = SelfImprovementHistory(path)
    history.append_memory(
        SelfImprovementMemoryRecord(
            outcome="PASS",
            cause="gate passed",
            improvements=("keep bounded checks",),
            next_action="continue next loop",
        )
    )

    assert history.load() == ()
    assert history.load_memory()[0].outcome == "PASS"


def test_cycle_memory_is_bounded(tmp_path):
    path = tmp_path / "memory.jsonl"
    history = SelfImprovementHistory(path, max_records=2)
    for outcome in ("FAIL", "PASS", "BLOCKED"):
        history.append_memory(
            SelfImprovementMemoryRecord(
                outcome=outcome,
                cause=outcome,
                improvements=("bounded",),
                next_action="continue",
            )
        )

    memories = history.load_memory(limit=20)
    assert [item.outcome for item in memories] == ["PASS", "BLOCKED"]


def test_cycle_memory_feeds_next_instruction_without_recurring_pattern(tmp_path):
    path = tmp_path / "memory.jsonl"
    SelfImprovementHistory(path).append_memory(
        SelfImprovementMemoryRecord(
            outcome="PASS",
            cause="gate passed",
            improvements=("keep bounded checks",),
            next_action="continue next loop",
        )
    )

    augmented = _augment_instruction_with_history("next safe task", path)

    assert augmented.startswith("next safe task\n\n")
    assert "prior outcome=PASS" in augmented
    assert "next_action=continue next loop" in augmented


def test_cycle_memory_is_written_as_one_json_record_per_line(tmp_path):
    path = tmp_path / "memory.jsonl"
    history = SelfImprovementHistory(path)
    history.append_memory(
        SelfImprovementMemoryRecord(
            outcome="PASS",
            cause="gate passed",
            improvements=("bounded",),
            next_action="continue",
        )
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert isinstance(json.loads(lines[0]), dict)

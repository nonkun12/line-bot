import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage149_evolutionary_selection import (
    EvolutionPopulationEntry, EvolutionPopulationSnapshot,
)
from core.ai_factory_stage150_evolution_history import (
    EvolutionHistoryError, EvolutionHistoryLedger, EvolutionTrend,
)

SUITE = "a" * 64


def entry(candidate, generation, accuracy, instruction, safety=.99, latency=100, memory=512):
    return EvolutionPopulationEntry(
        candidate_id=candidate,
        generation=generation,
        parent_ids=("p1", "p2"),
        artifact_digest=(candidate.encode().hex() + "0" * 64)[:64],
        evidence_digest=(str(generation) + "e" * 64)[:64],
        evaluation_suite_digest=SUITE,
        fitness=Fitness(accuracy, instruction, safety, latency, memory, 0, SUITE),
    )


def snapshot(*entries):
    generations = tuple(sorted({item.generation for item in entries}))
    return EvolutionPopulationSnapshot(tuple(entries), (), generations, 64)


def test_detects_improvement_then_stagnation():
    ledger = EvolutionHistoryLedger()
    ledger.record_snapshot(snapshot(entry("g1", 1, .80, .80)))
    ledger.record_snapshot(snapshot(entry("g2", 2, .85, .84)))
    ledger.record_snapshot(snapshot(entry("g3", 3, .85, .84)))
    ledger.record_snapshot(snapshot(entry("g4", 4, .85, .84)))
    report = ledger.analyze(stagnation_window=2)
    assert report.trend is EvolutionTrend.STAGNANT
    assert report.improvement_events == 1
    assert report.current_stagnation_streak == 2
    assert report.stagnation_alert is True
    assert report.auto_advance is False


def test_detects_regression_without_erasing_prior_generations():
    ledger = EvolutionHistoryLedger()
    ledger.record_snapshot(snapshot(entry("g1", 1, .90, .90)))
    ledger.record_snapshot(snapshot(entry("g2", 2, .80, .80)))
    report = ledger.analyze()
    assert report.trend is EvolutionTrend.REGRESSING
    assert report.regression_alert is True
    assert tuple(item.generation for item in ledger.observations()) == (1, 2)


def test_rejects_duplicate_generation_and_suite_drift():
    ledger = EvolutionHistoryLedger()
    ledger.record_snapshot(snapshot(entry("g1", 1, .80, .80)))
    with pytest.raises(EvolutionHistoryError):
        ledger.record_snapshot(snapshot(entry("g1-again", 1, .81, .81)))
    different = EvolutionPopulationEntry(
        "g2", 2, ("p1", "p2"), "b" * 64, "c" * 64, "d" * 64,
        Fitness(.82, .82, .99, 100, 512, 0, "d" * 64),
    )
    with pytest.raises(EvolutionHistoryError):
        ledger.record_snapshot(snapshot(different))


def test_rejects_enabled_or_unverified_candidates():
    ledger = EvolutionHistoryLedger()
    active = EvolutionPopulationEntry(
        "active", 1, ("p1", "p2"), "b" * 64, "c" * 64, SUITE,
        Fitness(.8, .8, .99, 100, 512, 0, SUITE), enabled=True,
    )
    with pytest.raises(EvolutionHistoryError):
        ledger.record_snapshot(snapshot(active))


def test_history_capacity_fails_closed():
    ledger = EvolutionHistoryLedger(max_generations=2)
    ledger.record_snapshot(snapshot(entry("g1", 1, .8, .8)))
    ledger.record_snapshot(snapshot(entry("g2", 2, .81, .81)))
    with pytest.raises(EvolutionHistoryError):
        ledger.record_snapshot(snapshot(entry("g3", 3, .82, .82)))


def test_empty_history_is_insufficient_data():
    report = EvolutionHistoryLedger().analyze()
    assert report.trend is EvolutionTrend.INSUFFICIENT_DATA
    assert report.stagnation_alert is False

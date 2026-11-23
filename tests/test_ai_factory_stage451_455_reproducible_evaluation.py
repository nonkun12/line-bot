from core.ai_factory_stage451_455_reproducible_evaluation import (
    build_audit_chain, check_audit_chain, check_evaluator_pinning,
    check_rerun_equivalence, check_run_manifest, evaluate_stages_451_455,
)


def manifest():
    return {"run_id": "r-1", "protocol_id": "p", "protocol_version": "2",
            "task_set_id": "tasks", "evaluator_version": "eval-1", "model_id": "m",
            "model_revision": "rev-abc", "environment_id": "py-env-1",
            "random_seed": 42, "dependency_versions": {"python": "3.12", "pytest": "8"}}


def pins():
    return {k: manifest()[k] for k in ("protocol_id", "protocol_version", "task_set_id",
            "evaluator_version", "model_id", "model_revision", "environment_id")}


def run_rows():
    return [{"task_id": "t1", "output_sha256": "a" * 64, "score": 0.8},
            {"task_id": "t2", "output_sha256": "b" * 64, "score": 0.9}]


def test_451_requires_complete_reproducibility_manifest():
    assert check_run_manifest(manifest())["pass"]
    assert not check_run_manifest({**manifest(), "random_seed": True})["pass"]
    assert not check_run_manifest({**manifest(), "dependency_versions": {}})["pass"]


def test_452_compares_coverage_digests_and_scores():
    assert check_rerun_equivalence(run_rows(), run_rows())["pass"]
    changed = [dict(x) for x in run_rows()]
    changed[0]["score"] = 0.7
    assert not check_rerun_equivalence(run_rows(), changed)["pass"]
    changed[0]["score"] = 0.8
    changed[0]["output_sha256"] = "c" * 64
    assert not check_rerun_equivalence(run_rows(), changed)["pass"]


def test_453_requires_exact_version_pins():
    assert check_evaluator_pinning(manifest(), pins())["pass"]
    assert not check_evaluator_pinning(manifest(), {**pins(), "model_revision": "other"})["pass"]


def test_454_validates_hash_linked_audit_sequence():
    events = build_audit_chain([{"action": "evaluate"}, {"action": "score"}])
    assert check_audit_chain(events)["pass"]
    tampered = [dict(x) for x in events]
    tampered[0]["payload"] = {"action": "tampered"}
    assert not check_audit_chain(tampered)["pass"]


def test_455_aggregate_is_fail_closed_and_non_authorizing():
    events = build_audit_chain([{"action": "start"}, {"action": "finish"}])
    result = evaluate_stages_451_455(manifest=manifest(), expected_pins=pins(),
        first_run=run_rows(), second_run=run_rows(), audit_events=events)
    assert result["status"] == "PASS"
    assert result["provenance_verified"] is False
    assert result["reproducibility_certified"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64

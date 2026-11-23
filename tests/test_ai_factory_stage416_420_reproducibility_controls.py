from core.ai_factory_stage416_420_reproducibility_controls import (
    check_artifact_lineage,
    check_execution_environment,
    check_replay_consistency,
    check_reproduction_manifest,
    evaluate_stages_416_420,
)


D = "a" * 64


def test_stage_416_requires_complete_manifest_and_unique_input_refs():
    good = {"manifest_id": "m1", "schema_version": "1", "code_version": "abc",
            "runtime": "python", "config_digest": D,
            "inputs": [{"ref": "dataset", "sha256": D}]}
    assert check_reproduction_manifest([good])["pass"]
    bad = {**good, "inputs": [{"ref": "x", "sha256": "bad"},
                              {"ref": "x", "sha256": D}]}
    result = check_reproduction_manifest([bad])
    assert not result["pass"]
    assert any("duplicate" in error for error in result["errors"])


def test_stage_417_checks_artifact_lineage_shape():
    good = {"run_id": "r1", "input_refs": ["dataset"],
            "output_ref": "result", "output_sha256": D}
    assert check_artifact_lineage([good])["pass"]
    assert not check_artifact_lineage([{**good, "output_sha256": "bad"}])["pass"]


def test_stage_418_detects_different_output_digests_for_same_case():
    good = [{"case_id": "case-a", "run_id": "r1", "output_sha256": D},
            {"case_id": "case-a", "run_id": "r2", "output_sha256": D}]
    assert check_replay_consistency(good)["pass"]
    bad = [*good, {"case_id": "case-a", "run_id": "r3", "output_sha256": "b" * 64}]
    result = check_replay_consistency(bad)
    assert not result["pass"]
    assert "replay_output_mismatch:case-a" in result["errors"]


def test_stage_419_requires_declared_runtime_and_dependency_lock_digest():
    good = {"run_id": "r1", "runtime": "python", "platform": "linux",
            "dependency_lock_digest": D, "seed_policy": "fixed"}
    assert check_execution_environment([good])["pass"]
    assert not check_execution_environment([{**good, "dependency_lock_digest": "x"}])["pass"]


def test_stage_420_is_fail_closed_and_never_authorizes_execution_or_promotion():
    args = {
        "manifests": [{"manifest_id": "m1", "schema_version": "1", "code_version": "abc",
                       "runtime": "python", "config_digest": D,
                       "inputs": [{"ref": "dataset", "sha256": D}]}],
        "artifact_links": [{"run_id": "r1", "input_refs": ["dataset"],
                            "output_ref": "result", "output_sha256": D}],
        "replays": [{"case_id": "case-a", "run_id": "r1", "output_sha256": D},
                    {"case_id": "case-a", "run_id": "r2", "output_sha256": D}],
        "environments": [{"run_id": "r1", "runtime": "python", "platform": "linux",
                          "dependency_lock_digest": D, "seed_policy": "fixed"}],
    }
    result = evaluate_stages_416_420(**args)
    assert result["status"] == "PASS"
    assert result["proposal_only"] is True
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_416_420(**{**args, "artifact_links": []})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False

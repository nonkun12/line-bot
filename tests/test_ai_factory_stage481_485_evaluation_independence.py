from core.ai_factory_stage481_485_evaluation_independence import (
    check_calibration_evidence, check_dataset_lineage, check_external_reference,
    check_split_disjointness, evaluate_stages_481_485,
)


def test_481_rejects_overlap_and_duplicate_sample_ids():
    clean = {"train": ["a", "b"], "test": ["c"]}
    assert check_split_disjointness(clean, required_splits=["train", "test"])["pass"]
    assert not check_split_disjointness(
        {"train": ["a", "b"], "test": ["b", "c"]},
        required_splits=["train", "test"])["pass"]


def test_482_requires_unique_dataset_versions_and_lineage():
    rows = [{"dataset_id": "d", "version": "1", "parent_ref": "p"},
            {"dataset_id": "d", "version": "2", "parent_ref": "v1"}]
    assert check_dataset_lineage(rows, required_fields=["parent_ref"])["pass"]
    assert not check_dataset_lineage([rows[0], rows[0]],
                                     required_fields=["parent_ref"])["pass"]


def test_483_enforces_calibration_sample_and_error_limits():
    data = {"sample_count": 100, "error": 0.04, "method_id": "m",
            "dataset_ref": "d", "evaluator_ref": "e"}
    assert check_calibration_evidence(data, minimum_samples=50,
                                      maximum_error=0.05)["pass"]
    assert not check_calibration_evidence({**data, "error": 0.1},
                                          minimum_samples=50,
                                          maximum_error=0.05)["pass"]


def test_484_requires_compatible_external_reference():
    data = {"reference_id": "r", "source_id": "s", "version": "1",
            "retrieval_ref": "url-or-archive", "protocol_id": "p",
            "metric_id": "accuracy", "score": 0.8}
    assert check_external_reference(data, expected_protocol_id="p",
                                    expected_metric_id="accuracy")["pass"]
    assert not check_external_reference({**data, "metric_id": "other"},
                                        expected_protocol_id="p",
                                        expected_metric_id="accuracy")["pass"]


def test_485_aggregate_fails_closed_and_never_claims_verified_independence():
    result = evaluate_stages_481_485(
        splits={"train": ["a", "b"], "test": ["c"]},
        required_splits=["train", "test"],
        lineage_records=[{"dataset_id": "d", "version": "1", "parent_ref": "p"}],
        required_lineage_fields=["parent_ref"],
        calibration={"sample_count": 100, "error": 0.04, "method_id": "m",
                     "dataset_ref": "d", "evaluator_ref": "e"},
        minimum_calibration_samples=50, maximum_calibration_error=0.05,
        external_reference={"reference_id": "r", "source_id": "s", "version": "1",
            "retrieval_ref": "ref", "protocol_id": "p", "metric_id": "accuracy", "score": 0.8},
        expected_protocol_id="p", expected_metric_id="accuracy", unresolved_holds=[])
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["data_independence_verified"] is False
    assert result["external_validity_verified"] is False
    assert result["evidence_authenticity_verified"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64

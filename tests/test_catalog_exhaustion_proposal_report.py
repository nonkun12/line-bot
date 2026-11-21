import json

import pytest

from scripts.catalog_exhaustion_proposal_report import merge_review_candidates, main


def _report():
    return {
        "status": "REVIEW_REQUIRED",
        "reason": None,
        "candidate_count": 1,
        "candidates": [{
            "id": "review-coverage-gap-0123456789",
            "target_test": "tests/test_agent_runtime.py",
            "evidence": "core/agent_runtime.py:12",
            "source_function": "AgentRuntime.handle",
            "fingerprint": "a" * 64,
            "status": "REVIEW_REQUIRED",
            "instruction": "untrusted instructions must not be copied",
        }],
        "safety": {
            "read_only": True,
            "requires_human_review": True,
            "candidates_executable": False,
        },
    }


def test_surfaces_review_only_proposal_without_changing_trusted_status():
    result = merge_review_candidates({"status": "NO_TRUSTED_CANDIDATES", "proposal_count": 0, "proposals": []}, _report())
    assert result["status"] == "NO_TRUSTED_CANDIDATES"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result["review_only_proposal_count"] == 1
    row = result["review_only_proposals"][0]
    assert row["id"] == "review-coverage-gap-0123456789"
    assert row["target_test"] == "tests/test_agent_runtime.py"
    assert row["execution_authorized"] is False
    assert "untrusted instructions" not in json.dumps(row)


def test_no_safe_candidate_is_reported_without_proposals():
    result = merge_review_candidates(
        {"status": "NO_TRUSTED_CANDIDATES", "proposal_count": 0, "proposals": []},
        {"status": "NO_SAFE_CANDIDATE", "reason": "no_allowlisted_unreferenced_public_symbols_found", "candidate_count": 0, "candidates": []},
    )
    assert result["review_status"] == "NO_SAFE_CANDIDATE"
    assert result["review_only_proposals"] == []


@pytest.mark.parametrize("mutate", [
    lambda r: r["candidates"][0].update(target_test="../unsafe.py"),
    lambda r: r["candidates"][0].update(fingerprint="bad"),
    lambda r: r["safety"].update(candidates_executable=True),
    lambda r: r.update(candidate_count=2),
    lambda r: r["candidates"][0].update(id="../../unsafe"),
])
def test_invalid_analyzer_report_fails_closed(mutate):
    report = _report()
    mutate(report)
    with pytest.raises(ValueError):
        merge_review_candidates({"status": "NO_TRUSTED_CANDIDATES"}, report)


def test_cli_writes_reviewable_report_without_execution_authorization(tmp_path):
    proposals = tmp_path / "proposals.json"
    report = tmp_path / "analyzer.json"
    output = tmp_path / "out.json"
    proposals.write_text(json.dumps({"status": "NO_TRUSTED_CANDIDATES", "proposal_count": 0, "proposals": []}), encoding="utf-8")
    report.write_text(json.dumps(_report()), encoding="utf-8")
    assert main(["--proposals", str(proposals), "--catalog-report", str(report), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["review_only_proposal_count"] == 1
    assert result["review_only_proposals"][0]["execution_authorized"] is False

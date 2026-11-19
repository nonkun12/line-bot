from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_distributed_loop_hands_catalog_findings_to_review_candidate_pool():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Build review-only self-improvement candidate pool")
    end = text.index("- name: Upload review-only self-improvement candidates", start)
    step = text[start:end]

    history_adapter = step.index("scripts/self_improvement_candidate_adapter.py")
    catalog_adapter = step.index("scripts/catalog_exhaustion_candidate_adapter.py")
    candidate_bridge = step.index("scripts/review_candidate_bridge.py")

    assert history_adapter < catalog_adapter < candidate_bridge
    assert "set -euo pipefail" in step
    assert "--state /tmp/recovery-ai-state-readback.json" in step
    assert "--output /tmp/self-improvement-review-candidates.json" in step
    assert 'if [ -s /tmp/catalog-exhaustion-report.json ]; then' in step
    assert "--history /tmp/self-improvement-review-candidates.json" in step
    assert "--catalog-report /tmp/catalog-exhaustion-report.json" in step
    assert "--output /tmp/review-candidate-input.json" in step
    assert "cp /tmp/self-improvement-review-candidates.json /tmp/review-candidate-input.json" in step
    assert "--input /tmp/review-candidate-input.json" in step
    assert "--store artifacts/self-improvement-candidates/candidates.jsonl" in step
    assert "--summary artifacts/self-improvement-candidates/summary.md" in step

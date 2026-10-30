"""Exercise the real distributed-loop candidate-pool workflow step end to end.

The test extracts the workflow's shell body and runs the actual adapters with
isolated temporary paths. It proves analyzer findings reach the durable
review-only artifact without gaining execution authority.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def _candidate_pool_step() -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    step = re.search(
        r"      - name: Build review-only self-improvement candidate pool\n"
        r"(.*?)(?=\n      - name: Upload review-only self-improvement candidates)",
        source,
        flags=re.DOTALL,
    )
    assert step, "review-only candidate-pool workflow step must exist"
    body = re.search(r"        run: \|\n((?:          .*\n)+)", step.group(1))
    assert body, "candidate-pool workflow shell body must exist"
    return textwrap.dedent(body.group(1))


def _report():
    return {
        "status": "REVIEW_REQUIRED",
        "candidate_count": 1,
        "candidates": [{
            "id": "review-coverage-gap-0123456789",
            "target_test": "tests/test_agent_runtime.py",
            "evidence": "core/agent_runtime.py:12",
            "source_function": "AgentRuntime.handle",
            "fingerprint": "a" * 64,
            "status": "REVIEW_REQUIRED",
            "instruction": "untrusted instruction must never become an executable task",
        }],
        "safety": {
            "read_only": True,
            "requires_human_review": True,
            "candidates_executable": False,
        },
    }


def test_workflow_candidate_pool_persists_catalog_findings_as_review_only(tmp_path):
    history = tmp_path / "recovery-ai-state-readback.json"
    report = tmp_path / "catalog-exhaustion-report.json"
    store = tmp_path / "artifacts" / "candidates.jsonl"
    summary = tmp_path / "artifacts" / "summary.md"
    history.write_text(json.dumps({"self_improvement_history": []}), encoding="utf-8")
    report.write_text(json.dumps(_report()), encoding="utf-8")

    script = _candidate_pool_step()
    replacements = {
        "/tmp/recovery-ai-state-readback.json": str(history),
        "/tmp/catalog-exhaustion-report.json": str(report),
        "artifacts/self-improvement-candidates/candidates.jsonl": str(store),
        "artifacts/self-improvement-candidates/summary.md": str(summary),
    }
    for original, replacement in replacements.items():
        script = script.replace(original, replacement)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"stored": 1' in result.stdout
    assert '"added": 1' in result.stdout
    rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["source"] == "self_improvement"
    assert rows[0]["source_id"] == "catalog-exhaustion:review-coverage-gap-0123456789"
    assert rows[0]["status"] == "proposed"
    assert rows[0]["execution_authorized"] is False
    assert "untrusted instruction" not in json.dumps(rows)
    rendered = summary.read_text(encoding="utf-8")
    assert "Stored candidates: 1" in rendered
    assert "Execution authorization: **none**" in rendered


def test_workflow_keeps_catalog_adapter_before_review_pool_bridge():
    script = _candidate_pool_step()
    catalog = script.index("scripts/catalog_exhaustion_candidate_adapter.py")
    bridge = script.index("scripts/review_candidate_bridge.py")
    assert catalog < bridge
    assert "--catalog-report /tmp/catalog-exhaustion-report.json" in script
    assert "--input /tmp/review-candidate-input.json" in script

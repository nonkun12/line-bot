from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_distributed_loop_operation_contract_documents_canonical_entrypoints_and_safety():
    contract = (ROOT / "docs/distributed-ai-loop-operation-contract.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")

    assert ".github/workflows/distributed-autonomous-loop.yml" in contract
    assert "workflow_dispatch" in workflow
    assert "/distributed-loop max_tasks=1" in contract
    assert "max_tasks=4" in contract
    assert "autonomous-loop-state" in contract
    assert "Recovery AI" in contract
    assert "AUTO_APPLY_PATCH=false" in contract
    assert "AUTO_DEPLOY=false" in contract
    assert "Google Sheets" in contract
    assert "Do not loop-retry blindly" in contract


def test_distributed_loop_workflow_keeps_automatic_patch_and_deploy_disabled():
    workflow = (ROOT / ".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")

    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow
    assert "CONTROL_TOWER_KILL_SWITCH:" in workflow
    assert "Load durable loop state" in workflow
    assert "Check remote kill switch" in workflow

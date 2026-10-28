from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _step(source: str, name: str) -> str:
    start = source.index(f"      - name: {name}\n")
    end = source.find("\n      - name:", start + 1)
    return source[start:] if end < 0 else source[start:end]


def test_line_development_runtime_does_not_receive_github_token():
    source = (WORKFLOWS / "line-development.yml").read_text(encoding="utf-8")
    runtime = _step(source, "Run bounded multi-agent LINE development runtime")
    assert "GH_TOKEN:" not in runtime
    publish = _step(source, "Create or reuse GitHub PR")
    assert "GH_TOKEN: ${{ github.token }}" in publish


def test_line_development_dispatch_runtime_receives_no_github_token():
    source = (WORKFLOWS / "line-development-dispatch.yml").read_text(encoding="utf-8")
    runtime = _step(source, "Run bounded multi-agent LINE development runtime")
    assert 'GH_TOKEN: ""' in runtime
    publish = _step(source, "Create or reuse GitHub PR")
    assert "GH_TOKEN: ${{ github.token }}" in publish


def test_overnight_runtime_does_not_receive_github_token():
    source = (WORKFLOWS / "overnight-development.yml").read_text(encoding="utf-8")
    runtime = _step(source, "Run common guarded development runtime")
    assert "GH_TOKEN:" not in runtime
    publish = _step(source, "Create GitHub PR")
    assert "GH_TOKEN: ${{ github.token }}" in publish


def test_generated_code_workflows_do_not_persist_checkout_credentials():
    for name in (
        "line-development.yml",
        "line-development-dispatch.yml",
        "overnight-development.yml",
        "nightly-autonomous-worker.yml",
        "app-development.yml",
    ):
        source = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "persist-credentials: false" in source, name


def test_development_runtime_defers_push_to_trusted_workflow_steps():
    cases = (
        ("line-development.yml", "Run bounded multi-agent LINE development runtime"),
        ("line-development-dispatch.yml", "Run bounded multi-agent LINE development runtime"),
        ("overnight-development.yml", "Run common guarded development runtime"),
        ("nightly-autonomous-worker.yml", "Run common guarded distributed development runtime"),
    )
    for filename, step_name in cases:
        source = (WORKFLOWS / filename).read_text(encoding="utf-8")
        runtime = _step(source, step_name)
        assert 'AUTONOMOUS_PUBLISH_VIA_WORKFLOW: "true"' in runtime, filename

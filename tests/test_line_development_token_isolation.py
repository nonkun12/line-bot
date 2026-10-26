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

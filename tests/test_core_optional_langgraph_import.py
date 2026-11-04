"""Guard the lightweight Core import boundary when LangGraph is unavailable."""

from pathlib import Path
import subprocess
import sys


def test_autonomy_policy_import_does_not_require_langgraph():
    script = r"""
import importlib.abc
import sys

class BlockLangGraph(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "langgraph" or fullname.startswith("langgraph."):
            raise ModuleNotFoundError("simulated missing optional dependency: langgraph")
        return None

sys.meta_path.insert(0, BlockLangGraph())
from core.autonomy_policy import evaluate_job_autonomy
result = evaluate_job_autonomy({
    "stage": "review",
    "instruction": "Review the documentation structure and report findings.",
    "allowed_paths": ["docs/architecture.md"],
})
assert result["decision"] == "SAFE_CANDIDATE", result
"""
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, (
        f"lightweight Core import failed without LangGraph:\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )

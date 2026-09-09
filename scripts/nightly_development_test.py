"""Safe smoke test for the nightly-development process.

Read-only by design: no production data, secrets, deployments, or source files are modified.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "app.py",
    "n8n_delegate.py",
    "internal_ask_route.py",
    "routes/dashboard.py",
    "routes/e2e_dashboard.py",
]

missing = [name for name in REQUIRED if not (ROOT / name).exists()]

print("NIGHTLY_DEVELOPMENT_TEST")
print(f"repository_root={ROOT}")
print(f"required_files={len(REQUIRED)}")
print(f"missing_files={missing}")
print("status=PASS" if not missing else "status=FAIL")

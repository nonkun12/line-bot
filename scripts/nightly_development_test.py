"""Safe smoke test for the nightly-development process.

Read-only by design: no production data, secrets, deployments, or source files are modified.
"""
from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "app.py",
    "n8n_delegate.py",
    "internal_ask_route.py",
    "routes/dashboard.py",
    "routes/e2e_dashboard.py",
]

missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
syntax_errors = []

for name in REQUIRED:
    path = ROOT / name
    if path.is_file():
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            syntax_errors.append(f"{name}: {exc.msg}")

passed = not missing and not syntax_errors

print("NIGHTLY_DEVELOPMENT_TEST")
print(f"repository_root={ROOT}")
print(f"required_files={len(REQUIRED)}")
print(f"missing_files={missing}")
print(f"syntax_errors={syntax_errors}")
print("status=PASS" if passed else "status=FAIL")

if not passed:
    sys.exit(1)

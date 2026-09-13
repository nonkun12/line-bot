# Autonomous development target

When generic model-based target selection cannot safely choose a file, autonomous development falls back to a small deterministic list of test-focused files.

The preferred target order is:

1. `tests/test_management_router.py`
2. `tests/test_agent_runtime.py`
3. `tests/test_line_development_runtime.py`

Only repository files already accepted by the guarded worker are eligible.
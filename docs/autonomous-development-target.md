# Autonomous development target

Autonomous runs should keep the target deterministic when the generic manager cannot safely select a file.

The preferred first target is `tests/test_management_router.py` for small, testable management-routing improvements. Subsequent runs may move to other safe specialist foundation files after tests and review gates pass.

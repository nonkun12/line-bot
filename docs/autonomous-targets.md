# Autonomous development targets

The autonomous scheduler must use an explicit safe target when generic target selection cannot produce a valid file.

Preferred rotation:
- `tests/test_management_router.py` — management routing regression coverage
- `tests/test_voice_contract.py` — AI SPEAKER contract coverage
- `core/management_router.py` — deterministic management routing improvements

Each run must make one small, testable change and pass the existing guarded test/review gates.
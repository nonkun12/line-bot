import hashlib
import json
import urllib.error

from scripts import loop_repair_authorization as repair


def valid_evidence(**overrides):
    evidence = {
        "task_id": "catalog-task-1",
        "instruction_sha256": "a" * 64,
        "base_sha": "b" * 40,
        "current_head_sha": "b" * 40,
        "failure_fingerprint": "c" * 64,
        "allowed_paths": ["tests/test_example.py"],
        "catalog_repair_approved": True,
        "execution_approved": True,
        "held": False,
        "working_tree_clean": True,
        "rea_status": "PRE_REPAIR_PASS",
        "failure_category": "test_regression",
        "repair_attempts": 0,
    }
    evidence.update(overrides)
    return evidence


def test_authorize_repair_accepts_exact_one_shot_envelope():
    result = repair.authorize_repair(valid_evidence())
    assert result["gate"] == "PASS"
    assert result["execution_authorized"] is True
    assert result["scope"] == "one_repair_attempt"
    assert result["allowed_paths"] == ["tests/test_example.py"]
    assert result["repair_attempts"] == 1


def test_authorize_repair_rejects_missing_separate_catalog_approval():
    result = repair.authorize_repair(valid_evidence(catalog_repair_approved=False))
    assert result["gate"] == "BLOCKED"
    assert result["execution_authorized"] is False


def test_authorize_repair_rejects_held_dirty_or_nonpass_rea():
    for changes in (
        {"held": True},
        {"working_tree_clean": False},
        {"rea_status": "NOT_REQUIRED"},
        {"rea_status": "FAIL"},
    ):
        result = repair.authorize_repair(valid_evidence(**changes))
        assert result["gate"] == "BLOCKED"


def test_authorize_repair_rejects_repeated_attempt_and_changed_head():
    assert repair.authorize_repair(valid_evidence(repair_attempts=1))["gate"] == "BLOCKED"
    assert repair.authorize_repair(valid_evidence(current_head_sha="d" * 40))["gate"] == "BLOCKED"


def test_authorize_repair_rejects_unknown_failure_and_unsafe_paths():
    assert repair.authorize_repair(valid_evidence(failure_category="permission_error"))["gate"] == "BLOCKED"
    for path in ("/tmp/out.py", "../escape.py", "tests\\\\escape.py", "tests/*.py", "tests//file.py"):
        assert repair.authorize_repair(valid_evidence(allowed_paths=[path]))["gate"] == "BLOCKED"


def test_authorize_repair_binds_canonical_sorted_paths():
    result = repair.authorize_repair(valid_evidence(allowed_paths=["z/test.py", "a/test.py"]))
    expected = hashlib.sha256(
        json.dumps(["a/test.py", "z/test.py"], separators=(",", ":")).encode()
    ).hexdigest()
    assert result["allowed_paths"] == ["a/test.py", "z/test.py"]
    assert result["allowed_paths_sha256"] == expected


def test_consume_repair_authorization_requires_pass_and_token(monkeypatch):
    result = repair.consume_repair_authorization(
        {"gate": "BLOCKED", "execution_authorized": False}, token=""
    )
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "repair_authorization_not_consumable"


def test_consume_repair_authorization_records_unique_ref(monkeypatch):
    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "ref": captured["payload"]["ref"],
                "object": {"sha": "b" * 40},
            }).encode()

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(repair.urllib.request, "urlopen", fake_urlopen)
    authorization = repair.authorize_repair(valid_evidence())
    result = repair.consume_repair_authorization(authorization, token="test-token")
    assert result["gate"] == "PASS"
    assert result["marker_ref"].startswith("refs/heads/rsi-repair-consumed/")
    assert captured["payload"]["sha"] == "b" * 40
    assert captured["url"].endswith("/repos/nonkun12/line-bot/git/refs")


def test_consume_repair_authorization_rejects_duplicate_marker(monkeypatch):
    def duplicate(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 422, "exists", {}, None)

    monkeypatch.setattr(repair.urllib.request, "urlopen", duplicate)
    authorization = repair.authorize_repair(valid_evidence())
    result = repair.consume_repair_authorization(authorization, token="test-token")
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "repair_attempt_already_consumed"

import json

import pytest

from core.local_review_jobs import (
    REVIEW_JOB_TYPE,
    build_review_payload,
    enqueue_local_review,
)


BASE = "a" * 40
HEAD = "b" * 40


def test_payload_contains_only_allowlisted_review_metadata():
    payload = json.loads(build_review_payload("nonkun12/line-bot", BASE, HEAD))
    assert payload == {
        "schema_version": 1,
        "kind": REVIEW_JOB_TYPE,
        "repository": "nonkun12/line-bot",
        "base_sha": BASE,
        "head_sha": HEAD,
    }
    assert "command" not in payload
    assert "path" not in payload


@pytest.mark.parametrize(
    ("repository", "base", "head"),
    [
        ("other/repo", BASE, HEAD),
        ("nonkun12/line-bot", "short", HEAD),
        ("nonkun12/line-bot", BASE.upper(), HEAD),
        ("nonkun12/line-bot", BASE, BASE),
    ],
)
def test_payload_rejects_invalid_or_untrusted_inputs(repository, base, head):
    with pytest.raises(ValueError):
        build_review_payload(repository, base, head)


def test_enqueue_uses_dedicated_job_type_and_single_attempt(monkeypatch):
    captured = {}

    def fake_create_job(user_id, message, **kwargs):
        captured.update(user_id=user_id, message=message, kwargs=kwargs)
        return 17

    monkeypatch.setattr("core.local_review_jobs.create_job", fake_create_job)
    job_id = enqueue_local_review("U1", "nonkun12/line-bot", BASE, HEAD)

    assert job_id == 17
    assert captured["kwargs"]["job_type"] == REVIEW_JOB_TYPE
    assert captured["kwargs"]["source"] == "control_tower"
    assert captured["kwargs"]["max_retries"] == 1
    assert json.loads(captured["message"])["head_sha"] == HEAD


def test_enqueue_rejects_missing_user(monkeypatch):
    def unexpected_create_job(*args, **kwargs):
        raise AssertionError("must reject before touching DB")

    monkeypatch.setattr("core.local_review_jobs.create_job", unexpected_create_job)
    with pytest.raises(ValueError, match="user_id"):
        enqueue_local_review("", "nonkun12/line-bot", BASE, HEAD)

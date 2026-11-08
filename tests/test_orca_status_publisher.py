import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from scripts.orca_status_publisher import publish_snapshot, validate_snapshot


def payload():
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "run_id": "r1",
            "tasks": [{"id": "t1", "prompt": "SECRET"}], "dispatches": [], "workers": [],
            "streams": [{"key": "main_star_night", "label": "STAR-NIGHT", "kind": "main",
                         "status": "unknown", "task_count": 0, "dispatch_count": 0,
                         "worker_count": 0, "evidence": "no_matching_stream_metadata"}]}


def test_validate_snapshot_redacts_unknown_fields():
    clean = validate_snapshot(payload())
    assert clean["tasks"] == [{"id": "t1"}]
    assert len(clean["streams"]) == 1


@pytest.mark.parametrize("captured", [None, "not-a-date", "2026-01-01T00:00:00",
    (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),
    (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()])
def test_validate_snapshot_rejects_invalid_or_stale_timestamps(captured):
    data = payload()
    data["captured_at"] = captured
    with pytest.raises(ValueError): validate_snapshot(data)


def test_validate_snapshot_rejects_bad_collection_and_stream_shapes():
    data = payload()
    data["workers"] = ["not-object"]
    with pytest.raises(ValueError): validate_snapshot(data)
    data = payload()
    data["streams"][0]["key"] = "unexpected"
    with pytest.raises(ValueError): validate_snapshot(data)


def test_publish_snapshot_signs_sanitized_payload_and_posts_https():
    data = payload()
    captured = {}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def fake_urlopen(request, timeout):
        captured.update(url=request.full_url, body=request.data, signature=request.get_header("X-orca-signature"))
        return Response()
    with patch("scripts.orca_status_publisher.urlopen", fake_urlopen):
        assert publish_snapshot("https://dashboard.example", "secret", data) == 200
    assert captured["url"] == "https://dashboard.example/internal/orca/status"
    assert captured["signature"] == hmac.new(b"secret", captured["body"], hashlib.sha256).hexdigest()
    assert "SECRET" not in captured["body"].decode()


def test_publish_snapshot_refuses_http_and_missing_secret():
    with pytest.raises(ValueError): publish_snapshot("http://dashboard.example", "secret", payload())
    with pytest.raises(ValueError): publish_snapshot("https://dashboard.example", "", payload())


def test_validate_snapshot_accepts_sixth_core_vocabulary_stream():
    data = payload()
    data["streams"].append({
        "key": "side_core_vocabulary", "label": "英単語コア語彙", "kind": "side",
        "status": "observed", "task_count": 1, "dispatch_count": 0,
        "worker_count": 0, "evidence": "matched_runtime_records",
    })
    clean = validate_snapshot(data)
    assert len(clean["streams"]) == 2
    assert clean["streams"][1]["key"] == "side_core_vocabulary"

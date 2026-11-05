import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from scripts.orca_status_publisher import publish_snapshot, validate_snapshot


def test_validate_snapshot_requires_object_arrays():
    with pytest.raises(ValueError):
        validate_snapshot([])
    with pytest.raises(ValueError):
        validate_snapshot({"tasks": "not-a-list"})


def test_validate_snapshot_rejects_non_object_items():
    with pytest.raises(ValueError):
        validate_snapshot({"workers": ["worker"]})


def test_publish_snapshot_signs_exact_payload_and_posts_https():
    payload = {"tasks": [{"task_id": "t1"}], "dispatches": [], "workers": []}
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["signature"] = request.get_header("X-orca-signature")
        captured["timeout"] = timeout
        return Response()

    with patch("scripts.orca_status_publisher.urlopen", fake_urlopen):
        assert publish_snapshot("https://dashboard.example", "secret", payload) == 200

    expected = hmac.new(b"secret", captured["body"], hashlib.sha256).hexdigest()
    assert captured["url"] == "https://dashboard.example/internal/orca/status"
    assert captured["signature"] == expected
    assert json.loads(captured["body"]) == payload


def test_publish_snapshot_refuses_non_https_and_missing_secret():
    with pytest.raises(ValueError):
        publish_snapshot("http://dashboard.example", "secret", {})
    with pytest.raises(ValueError):
        publish_snapshot("https://dashboard.example", "", {})


def test_publish_snapshot_rejects_oversized_payload():
    with pytest.raises(ValueError):
        publish_snapshot(
            "https://dashboard.example",
            "secret",
            {"tasks": [{"data": "x" * 66000}]},
        )

from __future__ import annotations

import hashlib
import json
import subprocess

from scripts import loop_local_repair_adapter as adapter


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, *_args, **_kwargs):
        return self.response


class _Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    target = root / "tests" / "test_example.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tests/test_example.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return root, base


def _request(base, instruction="Add a regression assertion."):
    return {
        "task_id": "adapter-test",
        "instruction": instruction,
        "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "allowed_paths": ["tests/test_example.py"],
        "base_sha": base,
        "failure_fingerprint": "f" * 64,
        "repair_attempt": 1,
        "provider_policy": "provider_free_only",
    }


def test_local_adapter_applies_only_a_valid_allowlisted_patch(monkeypatch, tmp_path):
    root, base = _repo(tmp_path)
    patch = (
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1 +1,2 @@\n"
        "-value = 1\n"
        "+value = 1\n"
        "+assert value == 1\n"
    )
    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *_a, **_k: _Opener(_Response({"response": patch})))
    result = adapter.create_local_repair_adapter(root)(_request(base))
    assert result["status"] == "PASS"
    assert result["provider"] == "local_ollama_only"
    assert result["changed_paths"] == ["tests/test_example.py"]
    assert "assert value == 1" in (root / "tests/test_example.py").read_text(encoding="utf-8")


def test_local_adapter_rejects_instruction_hash_mismatch_before_model_call(monkeypatch, tmp_path):
    root, base = _repo(tmp_path)
    called = []
    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *_a, **_k: called.append(True))
    request = _request(base)
    request["instruction"] = "tampered instruction"
    result = adapter.create_local_repair_adapter(root)(request)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "task_instruction_hash_mismatch"
    assert called == []


def test_local_adapter_rejects_patch_outside_allowlist_without_applying(monkeypatch, tmp_path):
    root, base = _repo(tmp_path)
    patch = (
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1 +1,2 @@\n"
        "-value = 1\n"
        "+value = 1\n"
        "+assert value == 1\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -0,0 +1 @@\n"
        "+unsafe = True\n"
    )
    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *_a, **_k: _Opener(_Response({"response": patch})))
    result = adapter.create_local_repair_adapter(root)(_request(base))
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "local_patch_paths_outside_allowlist"
    assert not (root / "app.py").exists()
    assert (root / "tests/test_example.py").read_text(encoding="utf-8") == "value = 1\n"


def test_local_adapter_fails_closed_when_local_model_is_unavailable(monkeypatch, tmp_path):
    root, base = _repo(tmp_path)

    def unavailable(*_args, **_kwargs):
        import urllib.error
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *_a, **_k: type("Opener", (), {"open": staticmethod(unavailable)})())
    result = adapter.create_local_repair_adapter(root)(_request(base))
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "local_model_unavailable_no_cloud_fallback"



def test_local_adapter_rejects_git_metadata_patch_headers(monkeypatch, tmp_path):
    root, base = _repo(tmp_path)
    patch = (
        "diff --git a/tests/test_example.py b/tests/test_example.py\n"
        "new file mode 120000\n"
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1 +1,2 @@\n"
        "-value = 1\n"
        "+value = 1\n"
        "+assert value == 1\n"
    )
    monkeypatch.setattr(adapter.urllib.request, "build_opener", lambda *_a, **_k: _Opener(_Response({"response": patch})))
    result = adapter.create_local_repair_adapter(root)(_request(base))
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "local_patch_paths_outside_allowlist"
    assert (root / "tests/test_example.py").read_text(encoding="utf-8") == "value = 1\n"


def test_local_adapter_rejects_git_directory_in_allowlist(tmp_path):
    root, base = _repo(tmp_path)
    result = adapter.create_local_repair_adapter(root)({
        **_request(base),
        "allowed_paths": [".git/config"],
    })
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "repair_paths_invalid"



def test_local_model_transport_refuses_redirects():
    handler = adapter._NoRedirectHandler()
    assert handler.redirect_request(
        None, None, 302, "Found", {}, "https://example.com/api/generate"
    ) is None



def test_local_adapter_preflight_requires_exact_model_without_proxy_or_redirect(monkeypatch, tmp_path):
    root, _base = _repo(tmp_path)
    response = _Response({"models": [{"name": adapter.LOCAL_MODEL}, {"name": "other:latest"}]})
    opener = _Opener(response)
    calls = []
    monkeypatch.setattr(
        adapter.urllib.request, "build_opener",
        lambda *args, **kwargs: calls.append((args, kwargs)) or opener,
    )
    result = adapter.create_local_repair_adapter(root).preflight()
    assert result["status"] == "PASS"
    assert result["model"] == adapter.LOCAL_MODEL
    assert len(calls) == 1
    assert any(isinstance(item, adapter.urllib.request.ProxyHandler) for item in calls[0][0])
    assert any(item is adapter._NoRedirectHandler for item in calls[0][0])

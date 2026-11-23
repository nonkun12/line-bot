"""Provider-free local repair adapter backed only by loopback Ollama.

This adapter is intentionally unavailable in hosted GitHub Actions unless a local
Ollama daemon is running on the same machine. It never accepts a configurable
remote host, never falls back to a metered provider, and never executes model
output as a command. The coordinator remains responsible for one-shot approval
and independent REA verification.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LOCAL_ENDPOINT = "http://127.0.0.1:11434/api/generate"
LOCAL_TAGS_ENDPOINT = "http://127.0.0.1:11434/api/tags"
LOCAL_MODEL = "lfm3:1.7b-qad-q4_0"
MAX_INSTRUCTION_CHARS = 12_000
MAX_FILE_CHARS = 80_000
MAX_PATCH_BYTES = 48_000
REQUEST_TIMEOUT_SECONDS = 120


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent a loopback model endpoint from redirecting requests off-device."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "reason_code": reason, "provider": "local_ollama_only"}


def _git(root: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _safe_paths(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not value or len(value) > 20:
        return None
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 240:
            return None
        if item.startswith("/") or "\\" in item or ":" in item:
            return None
        parts = item.split("/")
        if any(part in {"", ".", ".."} or part.lower() == ".git" for part in parts):
            return None
        if any(char in part for part in parts for char in "*?[]{}"):
            return None
        paths.append(item)
    if len(set(paths)) != len(paths):
        return None
    return sorted(paths)


def _extract_patch(response: str) -> str | None:
    if not isinstance(response, str) or len(response.encode("utf-8")) > MAX_PATCH_BYTES:
        return None
    text = response.strip()
    fenced = re.search(r"```(?:diff)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("--- ") or "\n+++ " not in text or "\n@@ " not in text:
        return None
    return text + "\n"


def _patch_paths(patch: str) -> list[str] | None:
    found: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("diff --git ", "index ", "new file mode ", "deleted file mode ", "old mode ", "new mode ", "rename from ", "rename to ", "copy from ", "copy to ")):
            return None
        if line.startswith("--- ") or line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0]
            if raw == "/dev/null":
                return None
            prefix = "a/" if line.startswith("--- ") else "b/"
            if not raw.startswith(prefix):
                return None
            path = raw[2:]
            if not path or path.startswith("/") or "\\" in path:
                return None
            if any(part in {"", ".", ".."} for part in path.split("/")):
                return None
            found.append(path)
    if not found or len(found) % 2 or any(found[i] != found[i + 1] for i in range(0, len(found), 2)):
        return None
    paths = sorted(set(found))
    return paths if len(paths) * 2 == len(found) else None


def _read_context(root: Path, paths: list[str]) -> dict[str, str] | None:
    context: dict[str, str] = {}
    for relative in paths:
        target = root / relative
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(root)
            current = root
            for part in relative.split("/"):
                current = current / part
                if current.is_symlink():
                    return None
            if not resolved.is_file():
                return None
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            return None
        if len(content) > MAX_FILE_CHARS:
            return None
        context[relative] = content
    return context


def create_local_repair_adapter(repo_root: str | Path):
    """Return a callable compatible with loop_repair_executor.execute_one_repair."""
    root = Path(repo_root).resolve()

    def preflight() -> dict[str, Any]:
        """Confirm the exact local model exists before consuming one-shot approval."""
        request_obj = urllib.request.Request(LOCAL_TAGS_ENDPOINT, method="GET")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler)
            with opener.open(request_obj, timeout=10) as response:
                if response.status != 200:
                    return _blocked("local_model_preflight_http_status")
                payload = json.loads(response.read().decode("utf-8"))
            models = payload.get("models") if isinstance(payload, dict) else None
            names = {
                item.get("name") for item in models
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            } if isinstance(models, list) else set()
            if LOCAL_MODEL not in names:
                return _blocked("required_local_model_not_installed")
            return {"status": "PASS", "provider": "local_ollama_only", "model": LOCAL_MODEL}
        except Exception:
            return _blocked("local_model_preflight_unavailable_no_cloud_fallback")

    def repair(request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict) or request.get("provider_policy") != "provider_free_only":
            return _blocked("provider_policy_invalid")
        paths = _safe_paths(request.get("allowed_paths"))
        if paths is None:
            return _blocked("repair_paths_invalid")
        instruction = request.get("instruction")
        instruction_sha = request.get("instruction_sha256")
        if (
            not isinstance(instruction, str) or not instruction.strip()
            or len(instruction) > MAX_INSTRUCTION_CHARS
            or not isinstance(instruction_sha, str)
            or hashlib.sha256(instruction.encode("utf-8")).hexdigest() != instruction_sha
        ):
            return _blocked("task_instruction_hash_mismatch")
        if request.get("repair_attempt") != 1:
            return _blocked("repair_attempt_invalid")

        head = _git(root, "rev-parse", "HEAD")
        status = _git(root, "status", "--porcelain", "--untracked-files=all")
        if head.returncode or head.stdout.strip() != request.get("base_sha") or status.returncode or status.stdout.strip():
            return _blocked("local_repository_not_clean_at_authorized_base")

        context = _read_context(root, paths)
        if context is None:
            return _blocked("repair_context_unreadable")
        prompt = (
            "You are a local, bounded regression-test repair assistant.\n"
            "Return ONLY a unified diff. Do not explain. Do not add files, delete files, "
            "rename files, alter configuration, access secrets, or change any path outside "
            "the exact allowlist. Preserve unrelated code. Make the smallest change that "
            "addresses the task. If the task cannot be safely completed, return NO_PATCH.\n\n"
            f"Task ID: {request.get('task_id', '')}\n"
            f"Failure fingerprint: {request.get('failure_fingerprint', '')}\n"
            f"Exact task instruction:\n{instruction}\n\n"
            f"Allowed paths: {json.dumps(paths, ensure_ascii=False)}\n"
            f"Current file contents:\n{json.dumps(context, ensure_ascii=False)}"
        )
        payload = json.dumps({
            "model": LOCAL_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 4096},
        }).encode("utf-8")
        request_obj = urllib.request.Request(
            LOCAL_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler)
            with opener.open(request_obj, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    return _blocked("local_model_http_status")
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError:
            return _blocked("local_model_unavailable_no_cloud_fallback")
        except (TimeoutError, OSError):
            return _blocked("local_model_request_failed")
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return _blocked("local_model_response_invalid")

        patch = _extract_patch(body.get("response") if isinstance(body, dict) else None)
        if patch is None:
            return _blocked("local_model_returned_no_valid_patch")
        patch_paths = _patch_paths(patch)
        if patch_paths is None or not set(patch_paths).issubset(paths):
            return _blocked("local_patch_paths_outside_allowlist")

        check = _git(root, "apply", "--check", input_text=patch)
        if check.returncode:
            return _blocked("local_patch_did_not_apply_cleanly")
        applied = _git(root, "apply", input_text=patch)
        if applied.returncode:
            return _blocked("local_patch_apply_failed")

        after_head = _git(root, "rev-parse", "HEAD")
        changed = _git(root, "diff", "--name-only")
        staged = _git(root, "diff", "--cached", "--name-only")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard")
        actual = sorted(set(changed.stdout.splitlines() + staged.stdout.splitlines() + untracked.stdout.splitlines()))
        if (
            after_head.returncode or after_head.stdout.strip() != request.get("base_sha")
            or changed.returncode or staged.returncode or untracked.returncode
            or not actual or not set(actual).issubset(paths)
            or actual != patch_paths
        ):
            return _blocked("local_patch_post_apply_scope_mismatch")
        return {
            "status": "PASS",
            "reason_code": "local_ollama_patch_applied_within_allowlist",
            "provider": "local_ollama_only",
            "model": LOCAL_MODEL,
            "changed_paths": actual,
        }

    repair.preflight = preflight
    return repair

"""Explicit LINE/Slack -> governed development command dispatcher."""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Optional

import httpx

from core.request_safety import is_non_execution_request


logger = logging.getLogger(__name__)

_DEV_PREFIX = re.compile(r"^(?:開発|dev)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
# Natural-language execution is limited to clear imperative requests that name
# a software target. Questions and exploratory wording remain ordinary chat.
_NATURAL_DEV_TARGET = re.compile(
    r"(?:アプリ|システム|機能|コード|リポジトリ|プログラム|ワークフロー|"
    r"LINE\s*AI\s*Secretary|line-bot|\.py|STAR[- ]?NIGHT|タスク枯渇対策|分散Loop|分散ループ|自己改善(?:AI)?|映像・音楽AI|映像AI|音楽AI|LINE全指示化)",
    re.IGNORECASE,
)
_NATURAL_DEV_ACTION = re.compile(
    r"(?:改善して|改善してください|改良して|改良してください|修正して|修正してください|"
    r"直して|直してください|追加して|追加してください|実装して|実装してください|"
    r"開発して|開発してください|構築して|構築してください|保守して|テストして|"
    r"テストを実行して|調査して|進めて|続けて|実行して|更新して|ブラッシュアップして)",
)
_NATURAL_DEV_QUESTION = re.compile(
    r"(?:教えて|方法|やり方|どうやって|できますか|可能ですか|おすすめ|比較|とは)",
)
_MAX_INSTRUCTION_LENGTH = 2000

# Keep this manifest aligned with the worker's protected paths and shared
# self-improvement policy. The worker performs its own independent validation.
_WORKER_PROTECTED_PATHS = {
    ".github", ".env", "config.py",
    "scripts/line_development_worker.py",
    "scripts/line_development_worker_safe.py",
    "scripts/line_development_worker_v2.py",
    "core/line_development_runtime.py",
    "scripts/run_minimal_autonomous_loop.py",
    "tests/test_minimal_autonomous_loop.py",
    "line_development.py",
    "git_safety.py", "patch_validator.py", "render_client.py",
}
_POLICY_PROTECTED_PATHS = {
    "internal_ask_route.py", "internal_push_route.py",
    "core/execution_safety.py", "core/agent_runtime.py",
    "core/management_safety.py", "core/self_improvement_policy.py",
    "core/hermes_advisor.py",
}
_ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt")


def _build_execution_manifest(token: str, repository: str) -> dict[str, str] | None:
    """Bind one dispatch to the exact main SHA and its bounded editable path manifest."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        ref_response = httpx.get(
            f"https://api.github.com/repos/{repository}/git/ref/heads/main",
            headers=headers,
            timeout=_DISPATCH_TIMEOUT_SECONDS,
        )
        if ref_response.status_code != 200:
            return None
        ref_payload = ref_response.json()
        base_sha = str(ref_payload.get("object", {}).get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            return None

        tree_response = httpx.get(
            f"https://api.github.com/repos/{repository}/git/trees/{base_sha}?recursive=1",
            headers=headers,
            timeout=_DISPATCH_TIMEOUT_SECONDS,
        )
        if tree_response.status_code != 200:
            return None
        tree_payload = tree_response.json()
        if tree_payload.get("truncated") is True:
            return None
        entries = tree_payload.get("tree")
        if not isinstance(entries, list):
            return None

        paths: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str) or not path.endswith(_ALLOWED_SUFFIXES):
                continue
            if (
                path in _WORKER_PROTECTED_PATHS
                or path in _POLICY_PROTECTED_PATHS
                or path.startswith((".github/", "secrets/", ".git/"))
            ):
                continue
            paths.append(path)
        paths = sorted(set(paths))
        if not paths:
            return None
        allowed_paths = __import__("json").dumps(
            paths, ensure_ascii=False, separators=(",", ":")
        )
        # GitHub workflow_dispatch limits all inputs together to 65,535 chars.
        if len(allowed_paths) > 40000:
            return None
        digest = __import__("hashlib").sha256(allowed_paths.encode("utf-8")).hexdigest()
        return {
            "base_sha": base_sha,
            "allowed_paths": allowed_paths,
            "allowed_paths_sha256": digest,
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None


_WORKFLOW_FILE = "line-development-dispatch.yml"
_DISPATCH_TIMEOUT_SECONDS = 10.0
_DISPATCH_ATTEMPTS = 3
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# LINE自動開発E2E本線確認
# LINE自動開発E2E最終確認
# LINE自動開発E2E再テスト
# LINE自動開発テスト


def extract_development_instruction(message: str) -> Optional[str]:
    """Return the explicit normal development instruction, or None."""
    text = str(message or "").strip()
    # Safety constraints take precedence over both prefixed and natural-language
    # commands. A "開発:" prefix must never override an explicit read-only request.
    if is_non_execution_request(text):
        return None
    match = _DEV_PREFIX.match(text)
    if match:
        instruction = match.group(1).strip()
        if not instruction:
            return ""
        return instruction[:_MAX_INSTRUCTION_LENGTH]

    # Allow direct LINE commands such as "このアプリを改善して" without
    # requiring a special prefix. Keep authorization in the dispatcher and
    # require both an imperative development verb and an explicit software target.
    if (
        _NATURAL_DEV_TARGET.search(text)
        and _NATURAL_DEV_ACTION.search(text)
        and not _NATURAL_DEV_QUESTION.search(text)
        and not is_non_execution_request(text)
    ):
        return text[:_MAX_INSTRUCTION_LENGTH]
    return None


def _is_authorized_user(user_id: str) -> bool:
    """Require an explicit allowlist; deny by default when it is not configured."""
    configured = os.environ.get("DEV_ALLOWED_USER_IDS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and str(user_id) in allowed


def dispatch_development_workflow(
    instruction: str,
    *,
    user_id: str,
    token: str | None = None,
    repository: str | None = None,
    authorized: bool = False,
) -> str:
    """Dispatch authorized development requests to the existing Secretary repository."""
    instruction = str(instruction or "").strip()
    request_id = uuid.uuid4().hex[:12]
    if is_non_execution_request(instruction):
        return "読み取り専用の依頼として受け付けました。開発ワークフローは起動していません。"
    if not instruction:
        return "開発指示が空です。『開発: ○○を実装して』の形式で指定してください。"

    if not authorized and not _is_authorized_user(user_id):
        logger.warning("line_dev_dispatch event=denied request_id=%s reason=allowlist", request_id)
        return "このユーザーには開発ワークフローの実行権限がありません。"

    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.error("line_dev_dispatch event=failed request_id=%s reason=missing_token", request_id)
        return "開発ワークフローを起動できません。GITHUB_TOKENが設定されていません。"

    # 新規アプリ作成も既存システムの保守・機能追加も同じ管理経路へ送る。
    # 実行承認はLINE allowlist認証済みの明示的な開発指示にだけ結び付ける。
    repository = repository or os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    manifest = _build_execution_manifest(token, repository)
    if manifest is None:
        logger.error("line_dev_dispatch event=failed request_id=%s reason=execution_manifest_unavailable", request_id)
        return "開発ワークフローを起動できません。mainのSHAまたは安全な編集範囲を確認できませんでした。"
    task_id = uuid.uuid4().hex
    instruction_digest = __import__("hashlib").sha256(instruction.encode("utf-8")).hexdigest()
    dispatch_url = (
        f"https://api.github.com/repos/{repository}"
        f"/actions/workflows/{_WORKFLOW_FILE}/dispatches"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": "main",
        "inputs": {
            "instruction": instruction,
            "user_id": str(user_id),
            "execution_approval": "APPROVE_EXECUTION",
            "task_id": task_id,
            "approval_task_id": task_id,
            "approval_instruction_sha256": instruction_digest,
            "approval_base_sha": manifest["base_sha"],
            "allowed_paths": manifest["allowed_paths"],
            "approval_allowed_paths_sha256": manifest["allowed_paths_sha256"],
        },
    }

    logger.info("line_dev_dispatch event=requested request_id=%s workflow=%s", request_id, _WORKFLOW_FILE)
    last_error: str | None = None
    for attempt in range(1, _DISPATCH_ATTEMPTS + 1):
        try:
            response = httpx.post(
                dispatch_url,
                json=payload,
                headers=headers,
                timeout=_DISPATCH_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = type(exc).__name__
            logger.warning("line_dev_dispatch event=network_error request_id=%s attempt=%s error=%s", request_id, attempt, last_error)
            if attempt < _DISPATCH_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            return f"開発ワークフローの起動に失敗しました: {last_error}"
        except Exception as exc:
            return f"開発ワークフローの起動に失敗しました: {type(exc).__name__}"

        logger.info("line_dev_dispatch event=github_response request_id=%s attempt=%s status=%s", request_id, attempt, response.status_code)
        if response.status_code == 204:
            logger.info("line_dev_dispatch event=accepted request_id=%s", request_id)
            return f"🚀 開発指示を受け付けました。GitHub Actionsで開発・テストを開始しました。\n通常のLINE会話とは分離して実行します。\n受付ID: {request_id}"

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _DISPATCH_ATTEMPTS:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(float(retry_after), 3.0) if retry_after else 0.5 * attempt
            except ValueError:
                delay = 0.5 * attempt
            time.sleep(max(delay, 0.1))
            continue

        detail = response.text.strip().replace("\n", " ")
        if len(detail) > 300:
            detail = detail[:300]
        if response.status_code in {401, 403}:
            logger.error("line_dev_dispatch event=failed request_id=%s reason=github_auth status=%s", request_id, response.status_code)
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（GitHub Token/権限を確認してください。受付ID: {request_id}）"
        logger.error("line_dev_dispatch event=failed request_id=%s reason=github_http status=%s", request_id, response.status_code)
        if detail:
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（{detail}、受付ID: {request_id}）"
        return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（受付ID: {request_id}）"

    return f"開発ワークフローの起動に失敗しました: {last_error or 'unknown error'}"

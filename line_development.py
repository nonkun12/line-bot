"""Explicit LINE/Slack -> governed development command dispatcher."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import httpx


_DEV_PREFIX = re.compile(r"^(?:開発|dev)\s*:\s*(.*?)\s*$", re.IGNORECASE | re.DOTALL)
# Natural-language execution is limited to clear imperative requests that name
# a software target. Questions and exploratory wording remain ordinary chat.
_NATURAL_DEV_TARGET = re.compile(
    r"(?:アプリ|システム|機能|コード|リポジトリ|プログラム|ワークフロー|"
    r"LINE\s*AI\s*Secretary|line-bot|\.py)",
    re.IGNORECASE,
)
_NATURAL_DEV_ACTION = re.compile(
    r"(?:改善して|改善してください|改良して|改良してください|修正して|修正してください|"
    r"直して|直してください|追加して|追加してください|実装して|実装してください|"
    r"開発して|開発してください|構築して|構築してください|保守して|テストして|"
    r"テストを実行して|調査して)",
)
_NATURAL_DEV_QUESTION = re.compile(
    r"(?:教えて|方法|やり方|どうやって|できますか|可能ですか|おすすめ|比較|とは)",
)
# Read-only, diagnostic, and explicitly non-mutating requests must never
# start the autonomous development workflow, even when they mention a code
# target and contain words such as "test" or "investigate".
_NON_EXECUTION_REQUEST = re.compile(
    r"(?:読み取り専用|変更(?:は)?せず|変更(?:は)?しないで|変更(?:は)?行わず|"
    r"変更禁止|コード変更.{0,30}(?:行わず|しないで|禁止)|"
    r"(?:PR作成|マージ|デプロイ).{0,30}(?:行わず|しないで|禁止)|"
    r"だけ(?:を)?(?:確認|報告)|受付結果.{0,30}だけ報告)",
    re.IGNORECASE,
)
_MAX_INSTRUCTION_LENGTH = 2000
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
    if _NON_EXECUTION_REQUEST.search(text):
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
        and not _NON_EXECUTION_REQUEST.search(text)
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
    if not instruction:
        return "開発指示が空です。『開発: ○○を実装して』の形式で指定してください。"

    if not authorized and not _is_authorized_user(user_id):
        return "このユーザーには開発ワークフローの実行権限がありません。"

    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "開発ワークフローを起動できません。GITHUB_TOKENが設定されていません。"

    # 新規アプリ作成も既存システムの保守・機能追加も受け付ける。
    # すべて同じ認可・GitHub Actionsの管理された開発フローへ送り、安全性は実行側で検査する。

    # 通常のLINE開発指示は、分類器の汎用判定に関わらず既存リポジトリへ送る。
    repository = repository or os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
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
        },
    }

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
            if attempt < _DISPATCH_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            return f"開発ワークフローの起動に失敗しました: {last_error}"
        except Exception as exc:
            return f"開発ワークフローの起動に失敗しました: {type(exc).__name__}"

        if response.status_code == 204:
            return "🚀 開発指示を受け付けました。GitHub Actionsで開発・テストを開始しました。\n通常のLINE会話とは分離して実行します。"

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
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（GitHub Token/権限を確認してください）"
        if detail:
            return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}（{detail}）"
        return f"開発ワークフローの起動に失敗しました: HTTP {response.status_code}"

    return f"開発ワークフローの起動に失敗しました: {last_error or 'unknown error'}"

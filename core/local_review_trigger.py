"""Explicit, fail-closed LINE trigger for Mac-local PR reviews."""
from __future__ import annotations

import os
import re
from typing import Any, Callable

import httpx

from core.local_review_jobs import enqueue_local_review

_REVIEW_COMMAND = re.compile(r"^ローカルレビュー\s+PR\s+#?([1-9][0-9]{0,6})$", re.IGNORECASE)
_ALLOWED_REPOSITORY = "nonkun12/line-bot"


def extract_local_review_pr(message: str) -> int | None:
    """Accept only a dedicated command; ordinary chat must not enqueue jobs."""
    match = _REVIEW_COMMAND.fullmatch(str(message or "").strip())
    return int(match.group(1)) if match else None


def _get_pr(repository: str, number: int, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.get(
        f"https://api.github.com/repos/{repository}/pulls/{number}",
        headers=headers,
        timeout=8.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


def dispatch_local_review(
    user_id: str,
    message: str,
    *,
    token: str = "",
    get_pr: Callable[[str, int, str], Any] | None = None,
    channel: str | None = None,
) -> str | None:
    """Queue one review for an authorized user; never executes or merges code."""
    pr_number = extract_local_review_pr(message)
    if pr_number is None:
        return None
    if channel != "line":
        return "ローカルレビュー依頼はLINEからのみ受け付けます。"

    allowed_users = {
        value.strip()
        for value in os.environ.get("LOCAL_REVIEW_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    }
    normalized_user = str(user_id or "").strip()
    if not allowed_users or normalized_user not in allowed_users:
        return "ローカルレビュー依頼は許可された利用者のみ実行できます。設定未確認の場合は受付しません。"

    repository = _ALLOWED_REPOSITORY
    getter = get_pr or _get_pr
    try:
        pr = getter(repository, pr_number, token)
        if not isinstance(pr, dict):
            raise ValueError("invalid GitHub response")
        if pr.get("state") != "open" or pr.get("merged") is True:
            return f"PR #{pr_number} はオープン状態ではないため、レビュー依頼を登録しません。"
        base = pr.get("base")
        head = pr.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise ValueError("missing base/head metadata")
        if not isinstance(base.get("sha"), str) or not isinstance(head.get("sha"), str):
            raise ValueError("missing full commit SHA")
        if not isinstance(head.get("repo"), dict) or head["repo"].get("full_name") != repository:
            return "許可されていないリポジトリ由来のPRです。レビュー依頼を登録しません。"
        if not isinstance(base.get("repo"), dict) or base["repo"].get("full_name") != repository:
            return "ベースリポジトリが許可リストと一致しません。レビュー依頼を登録しません。"
        job_id = enqueue_local_review(normalized_user, repository, base["sha"], head["sha"])
    except Exception:
        # Do not log or echo tokens, API response bodies, or raw exception text.
        return f"PR #{pr_number} のレビュー依頼を登録できませんでした。GitHub情報と設定を確認してください。"

    return (
        f"PR #{pr_number} のローカルレビュー依頼を登録しました（Job {job_id}）。"
        "Mac側ワーカーで1件ずつ実行します。レビュー結果の確認前にマージ／デプロイは行いません。"
    )


__all__ = ["dispatch_local_review", "extract_local_review_pr"]

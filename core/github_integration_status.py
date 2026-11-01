"""Deterministic, read-only status reporting for LINE -> GitHub development integration."""
from __future__ import annotations

import re
from pathlib import Path


_GITHUB_INTEGRATION_STATUS_RE = re.compile(
    r"(?:github|git\s*hub).{0,24}(?:連携|接続).{0,24}(?:状態|状況|有無|設定|使える|利用|有効|動作|確認)|"
    r"(?:連携|接続).{0,24}(?:状態|状況|有無|設定|使える|利用|有効|動作|確認).{0,24}(?:github|git\s*hub)",
    re.IGNORECASE,
)


def is_github_integration_status_request(message: str) -> bool:
    """Match explicit questions about GitHub integration configuration/status."""
    return bool(_GITHUB_INTEGRATION_STATUS_RE.search(str(message or "").strip()))


def build_github_integration_status_reply(
    *,
    token: str | None,
    allowed_user_ids: str | None,
    workflow_path: str | Path | None = None,
) -> str:
    """Describe configured prerequisites without claiming a live dispatch test."""
    token_present = bool(str(token or "").strip())
    allowlist_present = bool(
        {item.strip() for item in str(allowed_user_ids or "").split(",") if item.strip()}
    )
    path = Path(workflow_path) if workflow_path is not None else (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "line-development-dispatch.yml"
    )
    workflow_present = path.is_file()

    configured = token_present and allowlist_present and workflow_present
    lines = [
        "【GitHub連携の設定状況】",
        f"- GITHUB_TOKEN: {'設定あり' if token_present else '未設定'}",
        f"- DEV_ALLOWED_USER_IDS: {'設定あり' if allowlist_present else '未設定'}",
        f"- LINE開発用GitHub Actions workflow: {'リポジトリ内に存在' if workflow_present else '見つかりません'}",
        f"- 設定上の判定: {'必要な設定項目は揃っています' if configured else '不足している設定があります'}",
        "",
        "※Tokenの有効性・GitHub権限・Actions dispatchの実疎通は、この読み取り確認では未検証です。",
        "※この確認ではGitHub検索、Actions起動、コード変更、PR作成、マージ、デプロイは行っていません。",
    ]
    return "\n".join(lines)

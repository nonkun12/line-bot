import re
from typing import Any, Callable, Optional

CallMcpTool = Callable[[str, dict[str, Any]], Any]


_LATEST_COMMIT_PATTERNS = [
    r"最新コミット",
    r"latest commit",
    r"commit history",
    r"コミット履歴",
    r"最新のPR",
    r"最新のプルリク",
    r"最新のpull request",
]


def _is_latest_commit_request(text: str) -> bool:
    lower_text = text.lower()
    for pattern in _LATEST_COMMIT_PATTERNS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            return True
    return False


def handle_latest_commits(message: str) -> Optional[str]:
    if not _is_latest_commit_request(message):
        return None

    return "最新コミット取得機能はまだ準備中です。"


def handle_github_message(
    message: str,
    user_id: str,
    call_mcp_tool: Optional[CallMcpTool] = None,
) -> str:
    """
    Handle GitHub-related user messages.

    This is a skeleton implementation. Actual GitHub API calls are not
    implemented here yet.
    """

    text = (message or "").strip()

    if not text:
        return "GitHub Agentに質問してください。"

    latest_commits = handle_latest_commits(text)
    if latest_commits is not None:
        return latest_commits

    return "GitHub関連の処理を準備中です。"

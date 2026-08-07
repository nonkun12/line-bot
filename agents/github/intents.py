import re
from typing import Optional


_GITHUB_KEYWORDS = [
    "github",
    "git hub",
    "pull request",
    "pr",
    "issue",
    "commit",
    "コミット",
    "プルリク",
    "プルリクエスト",
    "リポジトリ",
    "repository",
    "repo",
    "変更履歴",
    "差分",
    "マージ",
    "レビュー",
    "ブランチ",
    "ファイル内容",
    "ファイルを表示",
]

_GITHUB_PATTERN = re.compile(
    r"(?:github|git[- ]?hub|pull request|\bpr\b|issue|commit|コミット|プルリク|プルリクエスト|リポジトリ|repository|repo|変更履歴|差分|マージ|レビュー|ブランチ|ファイル内容|ファイルを表示)",
    re.IGNORECASE,
)


def is_github_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    """Detect whether a user message is asking for GitHub-related functionality."""

    text = (raw_message or "").strip()
    if not text:
        return False

    lower_text = text.lower()

    if any(keyword in lower_text for keyword in _GITHUB_KEYWORDS):
        return True

    return bool(_GITHUB_PATTERN.search(text))


_ISSUE_OR_PR_KEYWORDS = [
    "pull request",
    "pr",
    "issue",
    "issues",
    "プルリク",
    "プルリクエスト",
    "イシュー",
]


def is_issue_or_pr_intent(raw_message: str) -> bool:
    """
    Detect whether a user message is asking about GitHub Issues or Pull
    Requests specifically.

    Phase3-5 scope: this only classifies intent. Fetching actual Issue/PR
    data from the GitHub API is not implemented yet - the GitHub Agent
    uses this to return an appropriate "not yet supported" reply instead
    of silently falling through to the generic unknown-command message.
    """

    text = (raw_message or "").strip()
    if not text:
        return False

    lower_text = text.lower()

    return any(keyword in lower_text for keyword in _ISSUE_OR_PR_KEYWORDS)

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


_PR_KEYWORDS = [
    "pull request",
    "pr",
    "プルリク",
    "プルリクエスト",
]

_ISSUE_KEYWORDS = [
    "issue",
    "issues",
    "イシュー",
]

_ISSUE_OR_PR_KEYWORDS = _PR_KEYWORDS + _ISSUE_KEYWORDS


def is_issue_or_pr_intent(raw_message: str) -> bool:
    """
    Detect whether a user message is asking about GitHub Issues or Pull
    Requests (either one).
    """

    text = (raw_message or "").strip()
    if not text:
        return False

    lower_text = text.lower()

    return any(keyword in lower_text for keyword in _ISSUE_OR_PR_KEYWORDS)


def is_pull_request_intent(raw_message: str) -> bool:
    """Detect whether a user message is asking about Pull Requests specifically."""

    text = (raw_message or "").strip()
    if not text:
        return False

    lower_text = text.lower()

    return any(keyword in lower_text for keyword in _PR_KEYWORDS)


def is_issue_intent(raw_message: str) -> bool:
    """
    Detect whether a user message is asking about Issues specifically
    (and is not also a Pull Request request).
    """

    text = (raw_message or "").strip()
    if not text:
        return False

    lower_text = text.lower()

    if any(keyword in lower_text for keyword in _PR_KEYWORDS):
        return False

    return any(keyword in lower_text for keyword in _ISSUE_KEYWORDS)

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

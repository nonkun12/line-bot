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

# Strip explicitly forbidden GitHub operations before intent detection. This
# handles enumerated constraints and the "一切行わないでください" form.
_NEGATED_OPERATION_LIST = re.compile(
    r"(?:GitHub(?:の)?検索|Actions起動|リポジトリ変更|コード変更|コード実行|"
    r"PR作成|プルリク作成|マージ|デプロイ|GitHub操作)"
    r"(?:[、,・ ]+(?:GitHub(?:の)?検索|Actions起動|リポジトリ変更|コード変更|"
    r"コード実行|PR作成|プルリク作成|マージ|デプロイ|GitHub操作))*"
    r"(?:などの操作)?は(?:一切)?(?:しないでください|行わず|行わないでください|"
    r"実行しないでください|禁止)",
    re.IGNORECASE,
)
_STATUS_ONLY_REQUEST = re.compile(
    r"(?:受付結果|受付状況).{0,40}(?:だけ|のみ).{0,20}(?:報告|確認)|"
    r"(?:連携状況|起動状況|GitHub連携の有無).{0,30}(?:だけ|のみ).{0,20}(?:報告|確認)",
    re.IGNORECASE,
)


def _github_intent_text(raw_message: str) -> str:
    """Remove only explicitly negated operation clauses before routing."""
    return _NEGATED_OPERATION_LIST.sub("", (raw_message or "").strip())


# Natural-language file content requests (e.g. "README.mdを見せて",
# "app.pyを表示して"). Shared with agents.github.handlers.handle_file_contents()
# so the pattern used to *detect* these requests (for routing) and the
# pattern used to *extract the path* (for handling) stay in sync - defined
# once here and reused, rather than duplicated.
_FILE_CONTENT_PATTERN = re.compile(
    r"(?:github\s*の)?(?P<path>[\w\-./]+\.[A-Za-z0-9]+)"
    r"(?:の(?:ファイル内容|内容))?を(?:見せて|表示して|教えて)",
    re.IGNORECASE,
)


def is_github_intent(raw_message: str, user_id: Optional[str] = None) -> bool:
    """Detect whether a user message is asking for GitHub-related functionality."""

    text = (raw_message or "").strip()
    if not text:
        return False

    # Status-only requests and forbidden operations must not trigger browsing.
    if _STATUS_ONLY_REQUEST.search(text):
        return False
    intent_text = _github_intent_text(text)
    lower_text = intent_text.lower()

    if any(keyword in lower_text for keyword in _GITHUB_KEYWORDS):
        return True

    if _GITHUB_PATTERN.search(intent_text):
        return True

    return bool(_FILE_CONTENT_PATTERN.search(intent_text))


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

    if _STATUS_ONLY_REQUEST.search(text):
        return False
    lower_text = _github_intent_text(text).lower()

    return any(keyword in lower_text for keyword in _ISSUE_OR_PR_KEYWORDS)


def is_pull_request_intent(raw_message: str) -> bool:
    """Detect whether a user message is asking about Pull Requests specifically."""

    text = (raw_message or "").strip()
    if not text or _is_status_only_request(text):
        return False

    if _STATUS_ONLY_REQUEST.search(text):
        return False
    lower_text = _github_intent_text(text).lower()

    return any(keyword in lower_text for keyword in _PR_KEYWORDS)


def is_issue_intent(raw_message: str) -> bool:
    """
    Detect whether a user message is asking about GitHub Issues or Pull
    Requests (and is not also a Pull Request request).
    """

    text = (raw_message or "").strip()
    if not text or _is_status_only_request(text):
        return False

    if _STATUS_ONLY_REQUEST.search(text):
        return False
    lower_text = _github_intent_text(text).lower()

    if any(keyword in lower_text for keyword in _PR_KEYWORDS):
        return False

    return any(keyword in lower_text for keyword in _ISSUE_KEYWORDS)

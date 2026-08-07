import re
from .client import GitHubClient
from typing import Any, Callable, Optional

CallMcpTool = Callable[[str, dict[str, Any]], Any]


def format_repo_info(repo_info: dict) -> str:
    return (
        "【GitHub Repository】\n"
        f"📦 {repo_info.get('full_name')}\n"
        f"🐍 Language: {repo_info.get('language')}\n"
        f"🌿 Branch: {repo_info.get('default_branch')}\n"
        f"⭐ Stars: {repo_info.get('stargazers_count')}\n"
        f"🔗 {repo_info.get('html_url')}"
    )


def format_commits(commits: list) -> str:
    lines = ["【Latest Commits】"]

    for commit in commits[:5]:
        sha = commit.get("sha", "")[:7]

        message = (
            commit.get("commit", {})
            .get("message", "")
            .split("\n")[0]
        )

        lines.append(
            f"- {sha}: {message}"
        )

    return "\n".join(lines)


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




def format_search_results(result: dict) -> str:
    if isinstance(result, list):
        items = result
    else:
        items = result.get("items", [])

    if not items:
        return "GitHub検索結果が見つかりませんでした。"

    lines = ["【GitHub Search Results】"]

    for i, item in enumerate(items[:5], start=1):
        lines.append(
            f"{i}. {item.get('full_name')}\n"
            f"   説明: {item.get('description')}\n"
            f"   ⭐ Stars: {item.get('stargazers_count')}\n"
            f"   🔗 {item.get('html_url')}"
        )

    return "\n".join(lines)


def handle_github_search(message: str):
    patterns = [
        r"githubで(.+)探して",
        r"githubで(.+)検索",
        r"github search (.+)",
        r"github repo (.+)",
    ]

    query = None

    for pattern in patterns:
        match = re.search(
            pattern,
            message,
            re.IGNORECASE
        )

        if match:
            query = match.group(1)
            break

    if not query:
        return None

    client = GitHubClient()

    result = client.search_repositories(query)

    return format_search_results(result)

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

    client = GitHubClient()

    if text.startswith("github repo"):
        repo_info = client.get_repo_info()
        return format_repo_info(repo_info)

    if text.startswith("github commits"):
        commits = client.get_latest_commits()
        return format_commits(commits)

    if text.startswith("github file"):
        parts = text.split()
        if len(parts) >= 3:
            filename = parts[2]
            content = client.get_file_contents(filename)
            return content
        return "ファイル名を指定してください。"

    latest_commits = handle_latest_commits(text)
    if latest_commits is not None:
        return latest_commits

    search_result = handle_github_search(text)
    if search_result is not None:
        return search_result

    return "GitHub Agent: 対応コマンド github repo / commits / file / search です。"

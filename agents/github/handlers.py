from typing import Any, Callable, Optional

CallMcpTool = Callable[[str, dict[str, Any]], Any]


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

    # TODO: Add GitHub intent detection and handling logic.
    return "GitHub関連の処理を準備中です。"

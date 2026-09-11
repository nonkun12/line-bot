"""App-development Agent LangGraph node."""

from __future__ import annotations

import os

from app_development import dispatch_app_development_workflow, extract_app_development_request


def app_development_agent_node(state):
    """Dispatch an authorized app-development request to GitHub Actions."""
    message = str(state.get("raw_message", ""))
    user_id = str(state.get("user_id", ""))
    requirement = extract_app_development_request(message)
    if requirement is None:
        text = "アプリ開発の依頼として認識できませんでした。"
    else:
        text = dispatch_app_development_workflow(
            requirement,
            user_id=user_id,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )

    results = dict(state.get("agent_results", {}))
    results["app_development"] = {"text": text}
    return {**state, "agent_results": results}

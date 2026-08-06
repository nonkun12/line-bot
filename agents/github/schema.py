"""
Schema definitions for GitHub Agent data structures.
"""

from typing import TypedDict, Any


class GitHubAgentResult(TypedDict):
    text: str
    structured: Any

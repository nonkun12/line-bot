"""
AI Fix Agent Schema
"""

from typing import TypedDict


class FixResult(TypedDict, total=False):

    summary: str

    patch: str

    modified_files: list[str]

    test_command: str

    commit_message: str

    deploy_required: bool

    confidence: float

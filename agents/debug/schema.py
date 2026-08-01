"""
AI Debug Agent Phase2: Schema定義

Agent間で受け渡すデータ構造を管理する。
"""

from typing import TypedDict, Optional


class ErrorInfo(TypedDict, total=False):
    """
    Collectorの出力
    """

    error_type: Optional[str]
    file: Optional[str]
    line: Optional[int]
    message: Optional[str]
    raw: Optional[str]


class AnalysisResult(TypedDict, total=False):
    """
    Analyzerの構造化出力
    """

    error_type: Optional[str]
    file: Optional[str]
    line: Optional[int]
    message: Optional[str]

    cause: Optional[str]
    fix_direction: Optional[str]


class FixResult(TypedDict, total=False):
    """
    Fix Agentの出力

    将来的にGroq Fix Agentへ接続する。
    """

    summary: Optional[str]

    patch: Optional[str]

    modified_files: list[str]

    test_command: Optional[str]

    commit_message: Optional[str]

    deploy_required: bool

    confidence: float


class TestResult(TypedDict, total=False):
    """
    Test Agentの出力
    """

    passed: bool

    failed_tests: list[str]

    logs: str


class DeployResult(TypedDict, total=False):
    """
    Deploy Agentの出力
    """

    commit: Optional[str]

    push: bool

    deploy: bool

    url: Optional[str]
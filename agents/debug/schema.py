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
    Test Agentの出力 (agents/test/node.py test_runner_node)

    patch未適用時 (skipped=True):
        skipped: True
        passed: None
        reason: "patch not applied"

    patch適用済みでpytestを実行した場合
    (agents/test/runner.py run_tests, skipped=False):
        skipped: False
        passed: bool
        returncode: Optional[int]
        stdout: str
        stderr: str
        timed_out: bool
    """

    skipped: bool

    passed: Optional[bool]

    reason: Optional[str]

    returncode: Optional[int]

    stdout: Optional[str]

    stderr: Optional[str]

    timed_out: Optional[bool]


class DeployResult(TypedDict, total=False):
    """
    Deploy Agentの出力 (agents/deploy/node.py deploy_node)

    commit未完了時:
        deployed: False
        skipped: True
        reason: "commit not completed"

    commit完了だがAUTO_DEPLOY無効(デフォルト)時:
        deployed: False
        pending: True
        reason: "waiting for manual approval"
        commit_hash: Optional[str]

    AUTO_DEPLOY有効時 (実際にRenderへデプロイをトリガー):
        deployed: bool
        pending: False
        deploy_id: Optional[str]
        status: Optional[str]
        commit_hash: Optional[str]
        reason: Optional[str] (トリガー失敗時のみ)
    """

    deployed: bool

    skipped: bool

    pending: bool

    reason: Optional[str]

    commit_hash: Optional[str]

    deploy_id: Optional[str]

    status: Optional[str]
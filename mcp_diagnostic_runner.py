"""Run bounded MCP diagnostics off the LINE webhook thread."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)


def format_mcp_diagnostic_report(report: dict) -> str:
    return (
        "MCP接続診断（読み取り専用）\n"
        f"HTTP health: {report['health']}\n"
        f"Database ready: {report['ready']}\n"
        f"MCP認証: {report['mcp_auth']}\n"
        f"tools/list: {report['tools_list']}\n"
        f"ツール数: {report['tool_count']}\n"
        f"所要時間: {report['elapsed_ms']} ms\n"
        f"総合判定: {report['status']}"
    )


class McpDiagnosticRunner:
    """Single-flight, process-local executor for slow read-only diagnostics.

    The worker is intentionally best-effort: a process restart can interrupt an
    in-flight diagnostic. The LINE webhook itself never waits for the 65s retry.
    """

    def __init__(self, executor=None):
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mcp-diagnostic"
        )
        self._lock = threading.Lock()
        self._active = False

    def submit(
        self,
        user_id: str,
        diagnose: Callable[[], dict],
        push: Callable[[str, str], None],
    ) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
        try:
            self._executor.submit(self._run, str(user_id), diagnose, push)
        except Exception:
            with self._lock:
                self._active = False
            logger.exception("MCP diagnostic background submission failed")
            raise
        return True

    def _run(self, user_id, diagnose, push):
        try:
            report = diagnose()
            push(user_id, format_mcp_diagnostic_report(report))
        except Exception:
            logger.exception("MCP diagnostic background task failed")
            try:
                push(
                    user_id,
                    "MCP接続診断に失敗しました。詳細はサーバーログを確認してください。",
                )
            except Exception:
                logger.exception("MCP diagnostic failure notification failed")
        finally:
            with self._lock:
                self._active = False


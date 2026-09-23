"""Read-only self-introduction for the registered AI agents.

The registry is the source of truth so newly registered agents appear automatically.
"""

from __future__ import annotations

from core.agents import AgentRequest
from graph.core_registry import build_core_agent_registry

_TRIGGER_RE = __import__("re").compile(
    r"(各\s*AI|全\s*AI|AI\s*全員|各\s*エージェント|全\s*エージェント).*(自己紹介|紹介して|役割|担当)"
    r"|((自己紹介|紹介して).*(各\s*AI|全\s*AI|AI\s*全員|各\s*エージェント|全\s*エージェント))"
)

_MANAGEMENT = (
    ("Management AI", "全体統括・タスク分解・AI間の調整"),
    ("開発AI", "実装・修正・PR作成"),
    ("TEST AI", "テスト実行・失敗分析"),
    ("検証AI", "要求・設計・実装結果の検証"),
    ("安全ゲート", "実差分・対象範囲・権限・テスト結果の安全確認"),
    ("自己改善AI", "過去の開発結果を分析し、開発ループを改善"),
)


def is_self_introduction_request(message: str) -> bool:
    return bool(_TRIGGER_RE.search(str(message).strip()))


def build_self_introduction() -> str:
    registry = build_core_agent_registry()
    lines = [
        "【AI役割分担】",
        "統括・開発・TEST・検証・安全・自己改善の責任境界を維持し、専門AIは担当領域を処理します。",
        "",
        "■ 開発基盤AI",
    ]
    for name, role in _MANAGEMENT:
        lines.append(f"・{name}: {role}")

    lines.extend(["", "■ 登録済み専門AI"])
    for name in registry.names():
        agent = registry.get(name)
        description = str(getattr(agent, "description", "")).strip() or "担当領域はエージェント定義に従います"
        status = "稼働" if bool(getattr(agent, "enabled", True)) else "停止"
        lines.append(f"・{name}: {description} [{status}]")

    lines.extend([
        "",
        "※専門AIの一覧・説明はAgent Registryから動的に取得します。新しいAIを登録すると、この一覧にも自動反映されます。",
    ])
    return "\n".join(lines)


def handle_self_introduction(message: str) -> str | None:
    if not is_self_introduction_request(message):
        return None
    return build_self_introduction()

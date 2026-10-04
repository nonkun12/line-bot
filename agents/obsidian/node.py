"""Guarded local Obsidian agent node."""
from __future__ import annotations

import re

from agents.obsidian.intents import is_obsidian_intent
from core.specialist_gate import assert_agent_approved
from core.obsidian import ObsidianError, ObsidianVault
from graph.state import AgentState


_MAX_CONTENT_CHARS = 20_000
_SAVE_RE = re.compile(
    r"^obsidian\s*(?:に|へ)\s*(?P<mode>保存|記録|追記|追加)\b\s+"
    r"(?P<path>[^\s:：]+\.md)"
    r"(?:\s*[:：]\s*|\s*\n\s*)"
    r"(?P<content>[\s\S]+)$",
    re.IGNORECASE,
)
_READ_RE = re.compile(
    r"^obsidian\s*(?:を|から)\s*(?:読む|読んで|表示して)\b\s+"
    r"(?P<path>[^\s:：]+\.md)\s*$",
    re.IGNORECASE,
)


def _response(state: AgentState, text: str, **metadata: object) -> AgentState:
    results = dict(state.get("agent_results", {}))
    results["obsidian"] = {"text": text, **metadata}
    return {**state, "agent_results": results}


def obsidian_agent_node(state: AgentState) -> AgentState:
    """Execute only the two explicit, bounded Obsidian operations."""
    assert_agent_approved("obsidian")

    message = str(state.get("raw_message", "") or "").strip()
    vault = ObsidianVault.from_env()
    if vault is None:
        return _response(
            state,
            "Obsidian連携は未設定です。OBSIDIAN_VAULT_PATHを設定してください。",
            success=False,
            reason="vault_not_configured",
        )

    if not is_obsidian_intent(message):
        return _response(state, "Obsidianの操作形式を理解できませんでした。", success=False)

    save_match = _SAVE_RE.fullmatch(message)
    if save_match:
        path = save_match.group("path")
        content = save_match.group("content")
        if len(content) > _MAX_CONTENT_CHARS:
            return _response(
                state,
                "安全上、1回のObsidian書き込みは20,000文字までです。",
                success=False,
                reason="content_too_large",
            )

        try:
            mode = save_match.group("mode")
            if mode in {"保存", "記録"} and vault.exists(path):
                return _response(
                    state,
                    "既存ノートの上書きは安全のため拒否しました。追記する場合は「Obsidianに追記 path.md: 内容」を使ってください。",
                    success=False,
                    reason="overwrite_blocked",
                )
            target = vault.write_note(path, content, append=mode in {"追記", "追加"})
        except (ObsidianError, OSError) as exc:
            return _response(
                state,
                f"Obsidianへの書き込みを停止しました: {exc}",
                success=False,
                reason="write_rejected",
            )
        return _response(
            state,
            f"Obsidianに保存しました: {target}",
            success=True,
            operation="append" if mode in {"追記", "追加"} else "create",
        )

    read_match = _READ_RE.fullmatch(message)
    if read_match:
        path = read_match.group("path")
        try:
            content = vault.read_note(path)
        except (ObsidianError, OSError) as exc:
            return _response(
                state,
                f"Obsidianの読み取りを停止しました: {exc}",
                success=False,
                reason="read_rejected",
            )
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + "\n\n[表示上限を超えたため省略]"
        return _response(state, content, success=True, operation="read")

    return _response(
        state,
        "形式: 「Obsidianに保存 notes/example.md: 内容」または「Obsidianを読む notes/example.md」",
        success=False,
        reason="invalid_command",
    )

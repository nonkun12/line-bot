"""Guarded local Obsidian agent node."""
from __future__ import annotations

import re

from agents.obsidian.intents import is_obsidian_intent, normalize_obsidian_command
from core.specialist_gate import assert_agent_approved, assert_specialist_capability
from core.obsidian import ObsidianError, ObsidianVault
from graph.state import AgentState


_MAX_CONTENT_CHARS = 20_000
_MAX_READ_RESULTS = 20
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
_SEARCH_RE = re.compile(
    r"^obsidian\s*(?:で|から)\s*(?:検索|探して)\b\s+(?P<keyword>[\s\S]{1,200})$",
    re.IGNORECASE,
)
_LIST_RE = re.compile(r"^obsidian\s*(?:の)?\s*(?:一覧|リスト)\s*$", re.IGNORECASE)


def _response(state: AgentState, text: str, **metadata: object) -> AgentState:
    results = dict(state.get("agent_results", {}))
    results["obsidian"] = {"text": text, **metadata}
    return {**state, "agent_results": results}


def obsidian_agent_node(state: AgentState) -> AgentState:
    """Execute bounded Obsidian operations only after explicit capability gating."""
    assert_agent_approved("obsidian")

    raw_message = str(state.get("raw_message", "") or "").strip()
    message = normalize_obsidian_command(raw_message) or raw_message
    vault = ObsidianVault.from_env()
    if vault is None:
        return _response(
            state,
            "Obsidian連携は未設定です。ローカル実行環境でOBSIDIAN_VAULT_PATHを設定してください。",
            success=False,
            reason="vault_not_configured",
        )

    if not is_obsidian_intent(raw_message):
        return _response(
            state,
            "Obsidianの操作形式を理解できませんでした。",
            success=False,
            reason="intent_rejected",
        )

    try:
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

            mode = save_match.group("mode")
            if mode in {"保存", "記録"} and vault.exists(path):
                return _response(
                    state,
                    "既存ノートの上書きは安全のため拒否しました。追記する場合は「Obsidianに追記 path.md: 内容」を使ってください。",
                    success=False,
                    reason="overwrite_blocked",
                )
            assert_specialist_capability("obsidian", "obsidian_write")
            target = vault.write_note(path, content, append=mode in {"追記", "追加"})
            return _response(
                state,
                f"Obsidianに保存しました: {target}",
                success=True,
                operation="append" if mode in {"追記", "追加"} else "create",
                path=path,
            )

        read_match = _READ_RE.fullmatch(message)
        if read_match:
            path = read_match.group("path")
            assert_specialist_capability("obsidian", "obsidian_read")
            content = vault.read_note(path)
            if len(content) > _MAX_CONTENT_CHARS:
                content = content[:_MAX_CONTENT_CHARS] + "\n\n[表示上限を超えたため省略]"
            return _response(state, content, success=True, operation="read", path=path)

        search_match = _SEARCH_RE.fullmatch(message)
        if search_match:
            keyword = search_match.group("keyword").strip()
            assert_specialist_capability("obsidian", "obsidian_read")
            matches = vault.search_notes(keyword, limit=_MAX_READ_RESULTS)
            if not matches:
                return _response(
                    state,
                    f"「{keyword}」に一致するObsidianノートはありませんでした。",
                    success=True,
                    operation="search",
                    count=0,
                )
            body = "\n".join(f"- {path}" for path in matches)
            return _response(
                state,
                f"Obsidian検索結果（{len(matches)}件以内）:\n{body}",
                success=True,
                operation="search",
                count=len(matches),
            )

        if _LIST_RE.fullmatch(message):
            assert_specialist_capability("obsidian", "obsidian_read")
            matches = vault.list_notes(limit=200)
            if not matches:
                return _response(
                    state,
                    "ObsidianにMarkdownノートはありませんでした。",
                    success=True,
                    operation="list",
                    count=0,
                )
            body = "\n".join(f"- {path}" for path in matches)
            return _response(
                state,
                f"Obsidianノート一覧（最大200件）:\n{body}",
                success=True,
                operation="list",
                count=len(matches),
            )
    except (ObsidianError, OSError) as exc:
        return _response(
            state,
            f"Obsidian操作を停止しました: {exc}",
            success=False,
            reason="operation_rejected",
        )

    return _response(
        state,
        "形式: 「Obsidianに保存 notes/example.md: 内容」「Obsidianに追記 notes/example.md: 内容」「Obsidianを読む notes/example.md」「Obsidianで検索 キーワード」「Obsidian一覧」",
        success=False,
        reason="invalid_command",
    )

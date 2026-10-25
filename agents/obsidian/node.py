"""Guarded local Obsidian agent node."""
from __future__ import annotations

import re

from agents.obsidian.intents import is_obsidian_intent, normalize_obsidian_command
from core.idea_ai import build_idea_card, parse_idea_command
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


def _related_note_candidates(vault: ObsidianVault, focus: str, *, exclude_path: str, limit: int = 5) -> list[tuple[str, list[str]]]:
    """Return explainable lexical candidates from real vault notes; never invent paths."""
    if not focus.strip():
        return []
    stopwords = {"する", "した", "して", "こと", "ため", "これ", "それ", "アイデア", "関連", "開発", "機能"}
    normalized = re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龠ー]+", " ", focus.casefold())
    tokens = [token for token in normalized.split() if len(token) >= 2 and token not in stopwords]
    # Japanese ideas are often written without spaces; add overlapping bigrams from
    # Japanese runs, while keeping the matched fragments visible as evidence.
    japanese_runs = re.findall(r"[ぁ-んァ-ヶ一-龠ー]{3,}", focus)
    for run in japanese_runs:
        for index in range(len(run) - 1):
            term = run[index:index + 2]
            if term not in stopwords:
                tokens.append(term)
    terms = list(dict.fromkeys(tokens))
    if not terms:
        return []

    scored: list[tuple[int, str, list[str]]] = []
    for path in vault.list_notes(limit=200):
        if path == exclude_path:
            continue
        try:
            body = vault.read_note(path).casefold()[:20_000]
        except (ObsidianError, OSError, UnicodeError):
            continue
        hits = [term for term in terms if term.casefold() in body]
        # Avoid noisy links: require two independent matches, or one distinctive
        # token of at least four characters.
        if len(hits) < 2 and not any(len(term) >= 4 for term in hits):
            continue
        scored.append((len(hits), path, hits[:5]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(path, hits) for _, path, hits in scored[:limit]]


def _attach_related_notes(content: str, candidates: list[tuple[str, list[str]]]) -> str:
    """Replace the pending placeholder with evidence-backed links or a clear no-match."""
    marker = "- まだ検索していません。実在するノートとの照合後にのみリンクを追加します。"
    if not candidates:
        replacement = "- 検索済み: 関連候補は見つかりませんでした（自動統合・リンク追加なし）。"
    else:
        lines = ["- 検索済み: 以下は本文中の一致語に基づく候補です（意味的関連の確定ではありません）。"]
        for path, hits in candidates:
            link = path[:-3] if path.lower().endswith(".md") else path
            evidence = "、".join(hits)
            lines.append(f"- [[{link}]] — 一致語: {evidence}")
        replacement = "\n".join(lines)
    content = content.replace(marker, replacement, 1)
    return content.replace("- related_notes_status: pending_search", "- related_notes_status: searched", 1)


def _response(state: AgentState, text: str, **metadata: object) -> AgentState:
    results = dict(state.get("agent_results", {}))
    results["obsidian"] = {"text": text, **metadata}
    return {**state, "agent_results": results}


def obsidian_agent_node(state: AgentState) -> AgentState:
    """Execute bounded Obsidian operations only after explicit capability gating."""
    assert_agent_approved("obsidian")

    raw_message = str(state.get("raw_message", "") or "")
    message = normalize_obsidian_command(raw_message) or raw_message
    vault = ObsidianVault.from_env()
    if vault is None:
        if parse_idea_command(raw_message) is not None:
            # Cloud-side capture queues the compact original command. Only the
            # authenticated Mac-local Bridge can write the actual vault.
            assert_specialist_capability("obsidian", "obsidian_write")
            try:
                from core.obsidian_bridge import enqueue_obsidian_request

                job_id = enqueue_obsidian_request(str(state.get("user_id", "") or ""), raw_message)
            except (ObsidianError, OSError):
                return _response(
                    state,
                    "アイデアの受付に失敗しました。原案はこのメッセージ内に残っています。Bridge設定を確認してください。",
                    success=False,
                    reason="bridge_queue_failed",
                )
            return _response(
                state,
                f"アイデアを受付しました（ID: {job_id}）。Obsidianへの保存はMac側Bridgeの処理待ちです。",
                success=True,
                operation="queued",
                status="pending",
                job_id=job_id,
            )
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
                # Explicit idea retries use a stable content-derived ID. Treat an exact
                # original already present in that card as an idempotent success; never
                # rewrite it or generalize this exception to ordinary Obsidian notes.
                original_idea = parse_idea_command(raw_message)
                if original_idea is not None and path.startswith("Ideas/Inbox/IDEA-"):
                    try:
                        existing = vault.read_note(path)
                    except (ObsidianError, OSError):
                        existing = ""
                    original_marker = str(build_idea_card(original_idea)["original_block"])
                    if original_marker in existing:
                        return _response(
                            state,
                            f"アイデアは既に保存済みです（重複保存を防止）: {path}",
                            success=True,
                            operation="duplicate",
                            path=path,
                            duplicate=True,
                        )
                return _response(
                    state,
                    "既存ノートの上書きは安全のため拒否しました。追記する場合は「Obsidianに追記 path.md: 内容」を使ってください。",
                    success=False,
                    reason="overwrite_blocked",
                )
            assert_specialist_capability("obsidian", "obsidian_write")
            original_idea = parse_idea_command(raw_message)
            if original_idea is not None and path.startswith("Ideas/Inbox/IDEA-"):
                candidates = _related_note_candidates(vault, original_idea, exclude_path=path)
                content = _attach_related_notes(content, candidates)
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

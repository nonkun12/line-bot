"""Shared fail-closed guard for explicitly read-only LINE requests."""
from __future__ import annotations

import re


_READ_ONLY_REQUEST = re.compile(
    r"(?:読み取り専用|read[- ]only)|"
    r"(?:変更|コード変更|コードの変更|リポジトリ変更).{0,40}(?:せず|しないで|行わず|行わない|禁止)|"
    r"(?:GitHub(?:の)?検索|Actions起動|コード変更|PR作成|プルリク作成|マージ|デプロイ)"
    r"(?:[、,・ ]+(?:GitHub(?:の)?検索|Actions起動|コード変更|PR作成|プルリク作成|マージ|デプロイ))*"
    r"(?:などの操作)?(?:は)?(?:一切)?(?:行わず|行わないでください|行わないで|しないでください|しないで|実行しないでください|禁止)|"
    r"(?:だけ(?:を)?(?:確認|報告)|結果だけ報告|受付結果.{0,40}だけ報告|"
    r"連携状況.{0,40}だけ報告|GitHub連携の有無.{0,30}だけ報告)",
    re.IGNORECASE,
)


def is_non_execution_request(message: str) -> bool:
    """Return True when the request explicitly prohibits execution or mutation."""
    return bool(_READ_ONLY_REQUEST.search(str(message or "").strip()))

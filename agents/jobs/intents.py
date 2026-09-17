"""Intent recognition for the job-seeking AI."""
from __future__ import annotations

import re


_PATTERNS = (
    re.compile(r"(求職|転職|就職|求人|仕事探し|仕事を探|採用|応募|履歴書|職務経歴書|志望動機|面接|キャリア)", re.IGNORECASE),
    re.compile(r"\b(?:job|jobs|career|resume|cv|interview|application)\b", re.IGNORECASE),
)


def is_job_seeking_intent(text: str) -> bool:
    value = text or ""
    return any(pattern.search(value) for pattern in _PATTERNS)


def classify_job_mode(text: str) -> str:
    value = (text or "").casefold()
    if any(k in value for k in ("求人", "仕事探し", "仕事を探", "job", "jobs")):
        return "search"
    if any(k in value for k in ("履歴書", "resume", "cv")):
        return "resume"
    if any(k in value for k in ("職務経歴書",)):
        return "career_history"
    if any(k in value for k in ("志望動機", "cover letter", "application")):
        return "application"
    if any(k in value for k in ("面接", "interview")):
        return "interview"
    if any(k in value for k in ("応募",)):
        return "application"
    return "career"


def _compact(text: str, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return normalized[:limit]


def extract_job_keywords(text: str) -> tuple[str, ...]:
    """Extract a small explicit keyword set without inventing preferences."""
    value = _compact(text, 500)
    hits: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,31}|[ぁ-んァ-ン一-龯]{2,12}", value):
        if token.casefold() in {"求人", "仕事探し", "転職", "就職", "履歴書", "志望動機", "面接"}:
            continue
        if token not in hits:
            hits.append(token)
        if len(hits) >= 8:
            break
    return tuple(hits)

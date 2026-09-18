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
    if "職務経歴書" in value:
        return "career_history"
    if any(k in value for k in ("志望動機", "cover letter", "application", "応募")):
        return "application"
    if any(k in value for k in ("面接", "interview")):
        return "interview"
    return "career"


def extract_job_keywords(text: str) -> tuple[str, ...]:
    value = re.sub(r"\s+", " ", (text or "").strip())[:500]
    hits: list[str] = []
    excluded = {"求人", "仕事探し", "転職", "就職", "履歴書", "志望動機", "面接"}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,31}|[ぁ-んァ-ン一-龯]{2,12}", value):
        if token.casefold() in excluded or token in hits:
            continue
        hits.append(token)
        if len(hits) >= 8:
            break
    return tuple(hits)

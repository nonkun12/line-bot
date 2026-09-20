"""Intent recognition and deterministic search-criteria parsing for the job-seeking AI."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re


_PATTERNS = (
    re.compile(r"(求職|転職|就職|求人|仕事探し|仕事を探|採用|応募|履歴書|職務経歴書|志望動機|面接|キャリア)", re.IGNORECASE),
    re.compile(r"\b(?:job|jobs|career|resume|cv|interview|application)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class JobSearchCriteria:
    """Explicit, conservatively parsed job-search constraints.

    Only values stated in recognizable labelled forms are populated. The parser
    intentionally does not infer salary, location, remote status, or skills.
    """

    occupation: str | None = None
    location: str | None = None
    salary_min_yen: int | None = None
    remote: str | None = None
    skills: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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
    excluded = {"求人", "仕事探し", "仕事を探", "転職", "就職", "履歴書", "志望動機", "面接"}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,31}|[ぁ-んァ-ン一-龯]{2,12}", value):
        if token.casefold() in excluded or token in hits:
            continue
        hits.append(token)
        if len(hits) >= 8:
            break
    return tuple(hits)


def _label_value(text: str, labels: tuple[str, ...]) -> str | None:
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{pattern})\s*[:：]?\s*([^,、\n]+)",
        str(text or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" \t")
    return value[:120] or None


def _salary_min_yen(text: str) -> int | None:
    match = re.search(
        r"年収\s*(?:下限|最低|希望)?\s*[:：]?\s*(\d{2,5}(?:\.\d+)?)\s*(万円|万|千円|円)",
        str(text or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).casefold()
    multiplier = 10_000 if unit in {"万", "万円"} else 1_000 if unit == "千円" else 1
    return int(value * multiplier)


def _remote_mode(text: str) -> str | None:
    value = str(text or "").casefold()
    if "フルリモート" in value or "完全リモート" in value:
        return "full_remote"
    if "リモート" in value or "在宅" in value:
        return "remote"
    if "出社" in value or "オフィス勤務" in value:
        return "onsite"
    return None


def _skills(text: str) -> tuple[str, ...]:
    value = _label_value(text, ("必須スキル", "スキル", "経験", "技術"))
    if not value:
        return ()
    parts = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"[,、/／]+", value)]
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part[:60])
        if len(unique) >= 8:
            break
    return tuple(unique)


def extract_job_search_criteria(text: str) -> JobSearchCriteria:
    """Parse only explicitly labelled job-search constraints."""
    return JobSearchCriteria(
        occupation=_label_value(text, ("希望職種", "職種")),
        location=_label_value(text, ("勤務地", "勤務地希望", "場所", "エリア")),
        salary_min_yen=_salary_min_yen(text),
        remote=_remote_mode(text),
        skills=_skills(text),
    )

"""Provider-neutral contracts and deterministic scoring helpers for the job-seeking AI."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class JobApplicationStage(str, Enum):
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    CLOSED = "closed"


@dataclass(frozen=True)
class JobSearchCriteria:
    keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    remote_ok: bool = False
    min_salary: int | None = None
    employment_types: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobPosting:
    job_id: str
    title: str
    company: str
    location: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    employment_type: str = ""
    remote: bool = False
    skills: tuple[str, ...] = ()
    url: str = ""
    source: str = ""


@dataclass(frozen=True)
class JobScore:
    job_id: str
    total: float
    keyword_match: float
    location_match: float
    salary_match: float
    skill_match: float
    remote_match: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobApplication:
    job_id: str
    stage: JobApplicationStage = JobApplicationStage.SAVED
    notes: str = ""
    next_action: str = ""


def score_job(posting: JobPosting, criteria: JobSearchCriteria) -> JobScore:
    """Score only against explicit criteria; no hidden preference is inferred."""
    title_text = f"{posting.title} {posting.company}".casefold()
    matched_keywords = [k for k in criteria.keywords if k.casefold() in title_text]
    keyword_score = len(matched_keywords) / len(criteria.keywords) if criteria.keywords else 1.0

    location_text = posting.location.casefold()
    matched_locations = [v for v in criteria.locations if v.casefold() in location_text]
    location_score = len(matched_locations) / len(criteria.locations) if criteria.locations else 1.0

    if criteria.min_salary is None:
        salary_score = 1.0
    elif posting.salary_max is not None:
        salary_score = 1.0 if posting.salary_max >= criteria.min_salary else 0.0
    elif posting.salary_min is not None:
        salary_score = 1.0 if posting.salary_min >= criteria.min_salary else 0.5
    else:
        salary_score = 0.0

    posting_skills = {skill.casefold() for skill in posting.skills}
    required = {skill.casefold() for skill in criteria.required_skills}
    skill_score = len(required & posting_skills) / len(required) if required else 1.0

    remote_score = 1.0 if not criteria.remote_ok or posting.remote else 0.0
    total = round(
        0.30 * keyword_score
        + 0.20 * location_score
        + 0.20 * salary_score
        + 0.25 * skill_score
        + 0.05 * remote_score,
        4,
    )

    reasons: list[str] = []
    if matched_keywords:
        reasons.append("キーワード一致: " + ", ".join(matched_keywords))
    if matched_locations:
        reasons.append("勤務地一致: " + ", ".join(matched_locations))
    if required and required <= posting_skills:
        reasons.append("必須スキルをすべて確認")
    if criteria.remote_ok and posting.remote:
        reasons.append("リモート条件に一致")
    return JobScore(
        job_id=posting.job_id,
        total=total,
        keyword_match=round(keyword_score, 4),
        location_match=round(location_score, 4),
        salary_match=round(salary_score, 4),
        skill_match=round(skill_score, 4),
        remote_match=round(remote_score, 4),
        reasons=tuple(reasons),
    )


def rank_jobs(postings: Iterable[JobPosting], criteria: JobSearchCriteria) -> tuple[JobScore, ...]:
    return tuple(sorted((score_job(p, criteria) for p in postings), key=lambda item: (-item.total, item.job_id)))

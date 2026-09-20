"""Provider-neutral contracts for real job-search sources.

The default implementation is intentionally offline/unavailable: no synthetic
job listings are produced when an external source is not configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agents.jobs.intents import JobSearchCriteria


@dataclass(frozen=True)
class JobListing:
    """One source-backed job listing; all identifying fields must come from the provider."""

    title: str
    company: str
    location: str
    url: str
    source: str
    salary: str | None = None

    def __post_init__(self) -> None:
        required = (
            ("title", self.title, 200),
            ("company", self.company, 200),
            ("location", self.location, 200),
            ("url", self.url, 500),
            ("source", self.source, 120),
        )
        for name, value, limit in required:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
            if len(value) > limit:
                raise ValueError(f"{name} exceeds {limit} characters")
        if not (self.url.startswith("https://") or self.url.startswith("http://")):
            raise ValueError("job listing URL must use http or https")
        if self.salary is not None:
            if not isinstance(self.salary, str) or len(self.salary) > 120:
                raise ValueError("salary exceeds 120 characters")


@dataclass(frozen=True)
class JobSearchResult:
    """Bounded provider response."""

    status: str
    listings: tuple[JobListing, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"ok", "unavailable", "error"}:
            raise ValueError("invalid job search status")
        if len(self.listings) > 20:
            raise ValueError("too many job listings")
        if any(not isinstance(item, JobListing) for item in self.listings):
            raise TypeError("listings must contain JobListing values")
        if not isinstance(self.message, str) or len(self.message) > 500:
            raise ValueError("job search message exceeds 500 characters")


class JobSearchProvider(Protocol):
    def search(self, criteria: JobSearchCriteria) -> JobSearchResult:
        ...


class UnavailableJobSearchProvider:
    """Default provider that refuses to fabricate listings."""

    def search(self, criteria: JobSearchCriteria) -> JobSearchResult:
        return JobSearchResult(
            status="unavailable",
            message="実求人ソース未接続",
        )


__all__ = [
    "JobListing",
    "JobSearchProvider",
    "JobSearchResult",
    "UnavailableJobSearchProvider",
]

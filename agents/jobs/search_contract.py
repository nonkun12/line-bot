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
    """One source-backed job listing; the URL and source must be provided by the provider."""

    title: str
    company: str
    location: str
    url: str
    source: str
    salary: str | None = None


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

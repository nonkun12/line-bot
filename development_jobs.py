"""Detect and enqueue explicit development requests from LINE."""

import re

import job_store


_DEVELOPMENT_PATTERNS = (
    re.compile(r"(?:アプリ|システム|サービス|ツール).*(?:作って|作成して|開発して|実装して|作りたい)"),
    re.compile(r"(?:作って|作成して|開発して|実装して).*(?:アプリ|システム|サービス|ツール)"),
    re.compile(r"(?:todo|to-do|webアプリ|ウェブアプリ).*(?:作って|作成して|開発して|実装して)", re.I),
)


def is_development_request(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _DEVELOPMENT_PATTERNS)


def enqueue_development_job(user_id: str, message: str) -> dict:
    job_id = job_store.create_job(
        user_id=user_id,
        message=message,
        job_type="development",
        source="line",
        max_retries=3,
    )
    return {"job_id": job_id, "status": "pending", "message": message}

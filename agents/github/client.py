"""GitHub API client scaffolding for the GitHub Agent."""

from __future__ import annotations

import os
import base64
from typing import Any
import requests


class GitHubClient:
    """A lightweight GitHub API client placeholder."""

    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.repo = (
            repo
            or os.environ.get("AI_REPORT_GITHUB_REPO")
            or "nonkun12/line-bot"
        )

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_repo_info(self) -> dict[str, Any]:
        if not self.repo:
            return {"error": "GITHUB_REPO is not configured"}

        url = f"https://api.github.com/repos/{self.repo}"

        try:
            response = requests.get(
                url,
                headers=self._build_headers(),
                timeout=10,
            )

            if response.status_code != 200:
                return {
                    "error": "GitHub API error",
                    "status": response.status_code,
                }

            return response.json()

        except Exception as e:
            return {"error": str(e)}

    def get_latest_commits(self, count: int = 5) -> list[dict[str, Any]]:
        if not self.repo:
            return [{"error": "GITHUB_REPO is not configured"}]

        url = (
            f"https://api.github.com/repos/"
            f"{self.repo}/commits?per_page={count}"
        )

        try:
            response = requests.get(
                url,
                headers=self._build_headers(),
                timeout=10,
            )

            if response.status_code != 200:
                return [{
                    "error": "GitHub API error",
                    "status": response.status_code,
                }]

            return response.json()

        except Exception as e:
            return [{"error": str(e)}]



    def search_repositories(self, query: str, count: int = 5) -> dict[str, Any]:
        """
        Search GitHub repositories.

        Always returns a dict with a consistent shape so callers never need
        to guess whether they received a list or a dict:

            {
                "ok": bool,
                "items": list[dict],
                "error": str | None,
                "status": int | None,
            }
        """

        url = "https://api.github.com/search/repositories"

        params = {
            "q": query,
            "per_page": count,
            "sort": "stars",
            "order": "desc",
        }

        try:
            response = requests.get(
                url,
                headers=self._build_headers(),
                params=params,
                timeout=10,
            )

            if response.status_code != 200:
                return {
                    "ok": False,
                    "items": [],
                    "error": "GitHub API error",
                    "status": response.status_code,
                }

            data = response.json()

            # GitHub's search endpoint returns {"items": [...]}, but we
            # defensively accept a bare list too in case the response
            # shape ever changes or is mocked differently in tests.
            if isinstance(data, dict):
                items = data.get("items", [])
            elif isinstance(data, list):
                items = data
            else:
                items = []

            return {
                "ok": True,
                "items": items,
                "error": None,
                "status": response.status_code,
            }

        except Exception as e:
            return {
                "ok": False,
                "items": [],
                "error": str(e),
                "status": None,
            }

    def get_file_contents(self, path: str) -> str:
        if not self.repo:
            return "GITHUB_REPO is not configured"

        url = (
            f"https://api.github.com/repos/"
            f"{self.repo}/contents/{path}"
        )

        try:
            response = requests.get(
                url,
                headers=self._build_headers(),
                timeout=10,
            )

            if response.status_code != 200:
                return f"GitHub API error: {response.status_code}"

            data = response.json()

            content = data.get("content", "")

            if data.get("encoding") == "base64":
                return base64.b64decode(
                    content
                ).decode("utf-8")

            return content

        except Exception as e:
            return str(e)


def get_default_github_client() -> GitHubClient:
    return GitHubClient()

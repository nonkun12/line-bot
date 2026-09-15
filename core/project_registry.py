"""Project registry for routing work to the correct software repository.

The registry is intentionally provider-neutral.  It separates the AI Secretary
itself from independently developed software and gives future agents a stable
way to resolve a project before changing anything.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectRecord:
    name: str
    repository: str
    project_type: str = "software"
    runtime_target: str = ""
    owner_scope: str = ""
    active_branch: str = "main"
    status: str = "active"
    last_successful_commit: str = ""
    supported_agents: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supported_agents"] = list(self.supported_agents)
        return data


DEFAULT_PROJECT = ProjectRecord(
    name="line-bot",
    repository="nonkun12/line-bot",
    project_type="ai-secretary",
    runtime_target="render",
    owner_scope="primary",
    active_branch="main",
    supported_agents=(
        "management",
        "architect",
        "implementer",
        "tester",
        "reviewer",
        "repairer",
        "github",
        "deployment",
    ),
)


class ProjectRegistry:
    """Load and resolve projects from a small JSON registry."""

    def __init__(self, records: list[ProjectRecord] | None = None) -> None:
        source = records if records is not None else [DEFAULT_PROJECT]
        self._records: dict[str, ProjectRecord] = {}
        self._by_repository: dict[str, ProjectRecord] = {}
        for record in source:
            self._register_record(record)

    def _register_record(self, record: ProjectRecord) -> None:
        if not isinstance(record, ProjectRecord):
            raise TypeError("project registry entries must be ProjectRecord instances")
        name = record.name.strip()
        repository = record.repository.strip()
        if not name:
            raise ValueError("project name is required")
        if not repository:
            raise ValueError(f"project repository is required: {name}")
        if name in self._records:
            raise ValueError(f"duplicate project name: {name}")
        if repository in self._by_repository:
            raise ValueError(f"duplicate project repository: {repository}")
        self._records[name] = record
        self._by_repository[repository] = record

    @classmethod
    def from_path(cls, path: str | Path) -> "ProjectRegistry":
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"project registry not found: {target}")
        if not target.is_file():
            raise ValueError(f"project registry path is not a file: {target}")
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("project registry must be a JSON list")
        records: list[ProjectRecord] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("project registry entries must be objects")
            if "name" not in item or "repository" not in item:
                raise ValueError("project registry entries require name and repository")
            supported = item.get("supported_agents", ())
            if not isinstance(supported, (list, tuple)):
                raise ValueError("supported_agents must be a list")
            records.append(
                ProjectRecord(
                    name=str(item["name"]).strip(),
                    repository=str(item["repository"]).strip(),
                    project_type=str(item.get("project_type", "software")),
                    runtime_target=str(item.get("runtime_target", "")),
                    owner_scope=str(item.get("owner_scope", "")),
                    active_branch=str(item.get("active_branch", "main")),
                    status=str(item.get("status", "active")),
                    last_successful_commit=str(item.get("last_successful_commit", "")),
                    supported_agents=tuple(str(value).strip() for value in supported if str(value).strip()),
                )
            )
        return cls(records)

    @classmethod
    def from_environment(cls) -> "ProjectRegistry":
        path = os.environ.get("PROJECT_REGISTRY_PATH", "").strip()
        return cls.from_path(path) if path else cls()

    def list_projects(self) -> list[ProjectRecord]:
        return list(self._records.values())

    def get(self, name: str) -> ProjectRecord | None:
        return self._records.get(str(name).strip())

    def resolve_repository(self, repository: str) -> ProjectRecord | None:
        return self._by_repository.get(str(repository).strip())

    def require(self, name: str) -> ProjectRecord:
        record = self.get(name)
        if record is None:
            raise KeyError(f"unknown project: {name}")
        return record

    def require_repository(self, repository: str) -> ProjectRecord:
        record = self.resolve_repository(repository)
        if record is None:
            raise KeyError(f"unknown repository: {repository}")
        return record


__all__ = ["ProjectRecord", "DEFAULT_PROJECT", "ProjectRegistry"]

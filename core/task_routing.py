"""Provider-neutral routing contracts for the universal Agent platform.

The classifier is deliberately deterministic for explicit request forms.  An
ambiguous request is returned as ``unknown`` rather than guessed.  Repository
resolution then fails closed unless a Project Registry entry is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .project_registry import ProjectRecord, ProjectRegistry


class TaskMode(str, Enum):
    SELF_IMPROVEMENT = "self_improvement"
    NEW_SOFTWARE = "new_software"
    EXISTING_SOFTWARE = "existing_software"
    AGENT_MANAGEMENT = "agent_management"
    NON_SOFTWARE = "non_software"
    NORMAL = "normal"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskClassification:
    mode: TaskMode
    confidence: str
    project_name: str | None = None
    project_repository: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ResolvedTarget:
    classification: TaskClassification
    project: ProjectRecord | None
    repository: str | None
    requires_repository: bool
    safe: bool
    reason: str = ""


class TaskClassifier:
    """Classify explicit work requests without silently selecting a project."""

    _SECRETARY_DEV_HINTS = (
        "line_development.py",
        "line-development",
        "line_development_worker",
        "core/",
        ".github/",
        "pytest",
        "e2e",
        "line-bot",
        "自分自身",
        "自己改良",
    )

    def classify(self, message: str) -> TaskClassification:
        text = str(message or "").strip()
        if not text:
            return TaskClassification(TaskMode.UNKNOWN, "none", reason="empty request")

        lowered = text.lower()

        if self._matches_any(text, ("自分自身を改善", "自分を改善", "自己改良", "line-botを改善", "line-botを改良")):
            return TaskClassification(TaskMode.SELF_IMPROVEMENT, "high", "line-bot", "nonkun12/line-bot", "explicit self-improvement")

        if self._matches_any(text, ("新しいagent", "新規agent", "agentを作", "agentを追加", "エージェントを作", "エージェントを追加")):
            return TaskClassification(TaskMode.AGENT_MANAGEMENT, "high", reason="explicit agent lifecycle request")

        if text.startswith("開発:") or lowered.startswith("dev:"):
            if self._matches_any(text, self._SECRETARY_DEV_HINTS):
                return TaskClassification(TaskMode.SELF_IMPROVEMENT, "high", "line-bot", "nonkun12/line-bot", "development request targets the Secretary")
            return TaskClassification(TaskMode.NEW_SOFTWARE, "high", reason="explicit development prefix for independent software")

        if self._matches_any(text, ("ソフトを作って", "アプリを作って", "システムを作って", "サービスを作って", "新規ソフト", "新規アプリ")):
            return TaskClassification(TaskMode.NEW_SOFTWARE, "medium", reason="new software language")

        if self._matches_any(text, ("調べてレポート", "レポートして", "分析して", "調査して", "データ分析", "資料を作って", "文書を作って")):
            return TaskClassification(TaskMode.NON_SOFTWARE, "high", reason="explicit non-software work")

        target_patterns = (
            r"([A-Za-z0-9_.\-/]+)\s*を?\s*(?:改良|改善|修正|保守|メンテナンス)",
            r"(?:改良|改善|修正|保守|メンテナンス)\s*[:：]?\s*([A-Za-z0-9_.\-/]+)",
        )
        for pattern in target_patterns:
            match = re.search(pattern, text)
            if match:
                return TaskClassification(
                    TaskMode.EXISTING_SOFTWARE,
                    "high",
                    project_name=match.group(1),
                    reason="explicit project maintenance form",
                )

        if self._matches_any(lowered, ("bug", "error", "exception")) and self._matches_any(text, ("直して", "修正して", "調べて")):
            return TaskClassification(TaskMode.EXISTING_SOFTWARE, "low", reason="maintenance wording without target")

        return TaskClassification(TaskMode.NORMAL, "low", reason="no governed work mode matched")

    @staticmethod
    def _matches_any(text: str, phrases: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(phrase.lower() in lowered for phrase in phrases)


class ProjectResolver:
    """Resolve task targets through the canonical Project Registry."""

    def __init__(self, registry: ProjectRegistry | None = None) -> None:
        self.registry = registry or ProjectRegistry()

    def resolve(self, classification: TaskClassification) -> ResolvedTarget:
        if classification.mode in {TaskMode.SELF_IMPROVEMENT, TaskMode.EXISTING_SOFTWARE}:
            project_name = classification.project_name or "line-bot"
            project = self.registry.get(project_name) or self.registry.resolve_repository(classification.project_repository or "")
            if project is None:
                return ResolvedTarget(classification, None, None, True, False, "unknown project; refusing repository guess")
            return self._project_target(classification, project, required=True)

        if classification.mode == TaskMode.NEW_SOFTWARE:
            return ResolvedTarget(classification, None, None, False, True, "new project requires repository creation stage")

        if classification.mode == TaskMode.AGENT_MANAGEMENT:
            return ResolvedTarget(classification, None, None, False, True, "agent lifecycle can proceed without a project target")

        if classification.mode == TaskMode.NON_SOFTWARE:
            return ResolvedTarget(classification, None, None, False, True, "artifact/task destination selected by planner")

        if classification.mode == TaskMode.UNKNOWN:
            return ResolvedTarget(classification, None, None, False, False, "unknown task mode")

        return ResolvedTarget(classification, None, None, False, True, "normal request does not require project resolution")

    @staticmethod
    def _project_target(classification: TaskClassification, project: ProjectRecord | None, required: bool) -> ResolvedTarget:
        if project is None:
            return ResolvedTarget(classification, None, None, required, False, "project registry target missing")
        if project.status not in {"active", "maintenance"}:
            return ResolvedTarget(classification, project, project.repository, required, False, f"project status is {project.status}")
        return ResolvedTarget(classification, project, project.repository, required, True, "resolved from Project Registry")


__all__ = ["TaskMode", "TaskClassification", "ResolvedTarget", "TaskClassifier", "ProjectResolver"]

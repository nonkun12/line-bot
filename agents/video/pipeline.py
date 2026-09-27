"""Bounded, provider-neutral video production planning.

This module deliberately separates *production planning* from external media
providers. The Video Agent can turn source text into a bounded storyboard and
provider requests without gaining arbitrary network or filesystem capabilities.
Provider adapters can be added behind an explicit safety-reviewed allowlist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


MAX_SCENES = 12
MAX_SCENE_PROMPT_CHARS = 1200
MAX_SOURCE_CHARS = 12000
MAX_TOTAL_DURATION_SECONDS = 600


@dataclass(frozen=True)
class VideoScene:
    scene_id: str
    narration: str
    visual_prompt: str
    duration_seconds: int = 8

    def __post_init__(self) -> None:
        if not self.scene_id.strip():
            raise ValueError("scene_id is required")
        if not self.narration.strip():
            raise ValueError("narration is required")
        if not self.visual_prompt.strip():
            raise ValueError("visual_prompt is required")
        if len(self.visual_prompt) > MAX_SCENE_PROMPT_CHARS:
            raise ValueError("visual_prompt is too long")
        if not 1 <= self.duration_seconds <= 60:
            raise ValueError("duration_seconds must be between 1 and 60")


@dataclass(frozen=True)
class VideoPlan:
    title: str
    source_summary: str
    scenes: tuple[VideoScene, ...]
    aspect_ratio: str = "16:9"

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.source_summary.strip():
            raise ValueError("source_summary is required")
        if not 1 <= len(self.scenes) <= MAX_SCENES:
            raise ValueError(f"scene count must be between 1 and {MAX_SCENES}")
        if sum(scene.duration_seconds for scene in self.scenes) > MAX_TOTAL_DURATION_SECONDS:
            raise ValueError("video plan exceeds duration limit")
        if self.aspect_ratio not in {"16:9", "9:16", "1:1"}:
            raise ValueError("unsupported aspect ratio")


@dataclass(frozen=True)
class VideoGenerationRequest:
    scene_id: str
    prompt: str
    duration_seconds: int
    aspect_ratio: str


@dataclass(frozen=True)
class VideoGenerationResult:
    scene_id: str
    provider: str
    status: str
    artifact_url: str | None = None


class VideoProvider(Protocol):
    name: str

    def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        ...


class VideoProviderUnavailable(RuntimeError):
    """Raised when no explicitly configured provider is available."""


class VideoProductionPipeline:
    """Convert a bounded VideoPlan into provider-neutral generation requests."""

    def __init__(self, providers: Sequence[VideoProvider] = ()) -> None:
        self._providers = tuple(providers)

    @property
    def providers(self) -> tuple[VideoProvider, ...]:
        return self._providers

    def generation_requests(self, plan: VideoPlan) -> tuple[VideoGenerationRequest, ...]:
        return tuple(
            VideoGenerationRequest(
                scene_id=scene.scene_id,
                prompt=scene.visual_prompt,
                duration_seconds=scene.duration_seconds,
                aspect_ratio=plan.aspect_ratio,
            )
            for scene in plan.scenes
        )

    def generate(self, plan: VideoPlan) -> tuple[VideoGenerationResult, ...]:
        if not self._providers:
            raise VideoProviderUnavailable(
                "no video provider is configured; planning is available without generation"
            )
        provider = self._providers[0]
        return tuple(
            provider.generate(request)
            for request in self.generation_requests(plan)
        )


def build_initial_plan(source_text: str, *, title: str = "AI Video", aspect_ratio: str = "16:9") -> VideoPlan:
    """Create a deterministic first-pass storyboard from source text.

    This is intentionally conservative: it does not call a model or provider.
    A later scenario-planning stage may replace these scenes after validating
    the model-produced structure.
    """
    source = str(source_text or "").strip()
    if not source:
        raise ValueError("source_text is required")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError("source_text exceeds the bounded input limit")

    chunks = [part.strip() for part in source.replace("\n", " ").split("。") if part.strip()]
    if not chunks:
        chunks = [source]
    chunks = chunks[:MAX_SCENES]

    scenes = tuple(
        VideoScene(
            scene_id=f"scene-{index}",
            narration=chunk,
            visual_prompt=(
                f"Cinematic visual interpretation of: {chunk}. "
                "Maintain coherent characters, setting, lighting and visual style."
            ),
        )
        for index, chunk in enumerate(chunks, start=1)
    )
    return VideoPlan(
        title=title.strip()[:200],
        source_summary=source[:1000],
        scenes=scenes,
        aspect_ratio=aspect_ratio,
    )

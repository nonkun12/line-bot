"""Provider boundary for Composer AI."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class CompositionRequest:
    prompt: str

@dataclass(frozen=True)
class CompositionResult:
    status: str
    message: str
    provider: str

class MusicGenerationProvider(Protocol):
    name: str
    def compose(self, request: CompositionRequest) -> CompositionResult: ...

class UnconfiguredMusicProvider:
    """Safe default: never claims that audio was generated."""
    name = "unconfigured"
    def compose(self, request: CompositionRequest) -> CompositionResult:
        return CompositionResult("not_configured", "作曲設計は作成できますが、音源生成プロバイダーはまだ未接続です。", self.name)

def build_composition_request(prompt: str) -> CompositionRequest:
    return CompositionRequest(prompt=str(prompt or "").strip()[:2000])

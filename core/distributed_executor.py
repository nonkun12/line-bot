"""Provider adapter for real-model distributed agent execution.

The executor is deliberately read-only: model output is returned as an AgentResult
and never interpreted as a tool call, shell command, file mutation, or git action.
Concrete repository-changing agents remain behind the existing guarded development
runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from ai_client import generate_chat_completion

from .multi_agent import AgentExecutor, AgentResult, AgentRole, AgentTask

ModelCall = Callable[[str], str]


class DistributedModelExecutionError(RuntimeError):
    """Raised when the configured model cannot produce usable text."""


@dataclass(frozen=True)
class AgentPromptPolicy:
    """Immutable prompt policy shared by all distributed role executions."""

    system_prompt: str = (
        "You are a bounded specialist inside a multi-agent development system. "
        "Return analysis and a concise action/result summary only. Never emit or "
        "request shell commands, file writes, git mutations, secrets, or tool calls. "
        "Repository-changing work is handled by a separate guarded executor."
    )

    def build(self, task: AgentTask) -> str:
        resources = ", ".join(sorted(task.resources)) or "none"
        dependencies = ", ".join(task.depends_on) or "none"
        return (
            f"{self.system_prompt}\n\n"
            f"Role: {task.role.value}\n"
            f"Task ID: {task.task_id}\n"
            f"Instruction: {task.instruction.strip()}\n"
            f"Resources: {resources}\n"
            f"Dependencies: {dependencies}\n"
            "Provide the result as plain text suitable for an AgentResult summary."
        )


def groq_model_call(prompt: str) -> str:
    """Call the existing application AI boundary and return assistant text only."""
    response = generate_chat_completion(
        messages=[
            {
                "role": "system",
                "content": AgentPromptPolicy().system_prompt,
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1200,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise DistributedModelExecutionError("AI provider returned no choices")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise DistributedModelExecutionError("AI provider returned empty content")
    return text.strip()


class DistributedAIExecutor(AgentExecutor):
    """Execute agent tasks through a real model without granting mutation tools."""

    def __init__(
        self,
        *,
        model_call: ModelCall | None = None,
        prompt_policy: AgentPromptPolicy | None = None,
        allowed_roles: Mapping[AgentRole, bool] | None = None,
    ) -> None:
        self._model_call = model_call or groq_model_call
        self._prompt_policy = prompt_policy or AgentPromptPolicy()
        self._allowed_roles = dict(allowed_roles) if allowed_roles is not None else None

    def execute(self, task: AgentTask) -> AgentResult:
        if self._allowed_roles is not None and not self._allowed_roles.get(task.role, False):
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary=f"distributed role is not enabled: {task.role.value}",
            )
        try:
            summary = self._model_call(self._prompt_policy.build(task))
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary=f"model execution failed: {type(exc).__name__}: {exc}",
            )
        if not isinstance(summary, str) or not summary.strip():
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary="model execution returned empty result",
            )
        return AgentResult(task_id=task.task_id, success=True, summary=summary.strip()[:4000])


__all__ = [
    "AgentPromptPolicy",
    "DistributedAIExecutor",
    "DistributedModelExecutionError",
    "groq_model_call",
]

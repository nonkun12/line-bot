"""Channel-independent AI Core package."""

from .agents import Agent, AgentRegistry, AgentRequest, AgentResponse
from .agent_specs import AgentLifecycle, AgentSpec, AgentSpecRegistry
from .agent_versioning import AgentVersion, AgentVersionRegistry
from .advisory_ai import DEFAULT_ADVISORY_MODEL, generate_advisory_text
from .agent_maintenance import AgentMaintenance, MaintenanceFinding, MaintenanceSeverity
from .agent_governance import AgentGovernance, AgentGovernanceRecord
from .agent_handoff import AgentHandoff, HandoffStatus
from .agent_handoff_coordinator import AgentHandoffCoordinator, HandoffDecision
from .creator_critic import CriticAgent, CriticEvaluation, CreatorAgent, CreatorCriticLoop, DuelResult, ImprovementCandidate
from .execution_pipeline import DefaultPlanner, ExecutionResult, Manager, WorkPlan, WorkRequest
from .gateway import AIGateway, AIRequest, AIResponse
from .channel import handle_channel_request
from .langgraph_adapter import agent_request_from_state, ai_request_from_state, response_text
from .langgraph_runtime import CoreGraphState, agent_node_name, build_core_graph
from .legacy_adapter import LegacyNodeAgent, build_legacy_registry
from .orchestration import ExternalWorkflow, WorkflowResult
from .project_registry import ProjectRecord, ProjectRegistry
from .review import (
    AICompetitionLoop,
    ReviewerRegistry,
    ReviewDecision,
    ReviewFinding,
    ReviewResult,
)
from .router import AgentRouter, RouteResult
from .self_improvement_distributed import DistributedSelfImprovementLoop, DistributedSelfImprovementResult
from .self_improvement_policy import SelfImprovementAssessment, SelfImprovementDecision, assess_self_improvement
from .structured_output import ParseAttempt, ParseResult, parse_json_object, parse_with_retries, require_fields
from .task_routing import ProjectResolver, ResolvedTarget, TaskClassification, TaskClassifier, TaskMode

__all__ = [
    "Agent", "AgentRegistry", "AgentRequest", "AgentResponse",
    "AgentLifecycle", "AgentSpec", "AgentSpecRegistry",
    "AgentVersion", "AgentVersionRegistry", "AgentMaintenance",
    "DEFAULT_ADVISORY_MODEL", "generate_advisory_text",
    "MaintenanceFinding", "MaintenanceSeverity", "AgentGovernance", "AgentGovernanceRecord",
    "AgentHandoff", "HandoffStatus", "AgentHandoffCoordinator", "HandoffDecision",
    "CreatorAgent", "CriticAgent", "CreatorCriticLoop", "ImprovementCandidate",
    "CriticEvaluation", "DuelResult", "Manager", "WorkRequest", "WorkPlan",
    "ExecutionResult", "DefaultPlanner", "TaskMode", "TaskClassification",
    "ResolvedTarget", "TaskClassifier", "ProjectResolver", "ProjectRecord",
    "ProjectRegistry", "SelfImprovementDecision", "SelfImprovementAssessment",
    "assess_self_improvement", "DistributedSelfImprovementLoop", "DistributedSelfImprovementResult",
    "ParseAttempt", "ParseResult", "parse_json_object",
    "parse_with_retries", "require_fields", "AgentRouter", "RouteResult",
    "AIGateway", "AIRequest", "AIResponse", "handle_channel_request",
    "CoreGraphState", "agent_node_name", "build_core_graph", "LegacyNodeAgent",
    "build_legacy_registry", "agent_request_from_state", "ai_request_from_state",
    "response_text", "ExternalWorkflow", "WorkflowResult", "AICompetitionLoop",
    "ReviewerRegistry", "ReviewDecision", "ReviewFinding", "ReviewResult",
]

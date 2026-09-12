"""LangGraph main graph definition.

The graph keeps the existing debug/fix pipeline while wiring every Core agent
that Supervisor can select into the compiled graph.
"""

from langgraph.graph import StateGraph, START, END

from graph.state import AgentState
from graph.supervisor import supervisor_node
from graph.router import route_from_supervisor
from graph.core_registry import build_core_agent_registry
from agents.app_development.node import app_development_agent_node
from agents.debug.node import debug_agent_node
from agents.memory.node import memory_agent_node
from agents.notes.node import notes_agent_node
from agents.github.node import github_agent_node
from agents.sheets.node import sheets_agent_node
from agents.normal.node import normal_agent_node
from agents.weather.node import weather_agent_node
from agents.english.node import english_learning_agent_node
from agents.stocks.node import agent as stocks_agent
from agents.news.node import agent as ai_news_agent
from agents.voice.node import agent as voice_agent
from dev_notes.wrappers.graph_node_wrapper import with_execution_logging
from dev_notes.factory import get_default_adapter


def _agent_node(agent):
    """Adapt a Core Agent to the LangGraph state contract."""
    def node(state: AgentState) -> AgentState:
        from core.agents import AgentRequest

        request = AgentRequest(
            user_id=str(state.get("user_id", "")),
            message=str(state.get("raw_message", "")),
            channel=str(state.get("channel", "unknown")),
            metadata=state.get("metadata", {}),
        )
        response = agent.handle(request)
        return {
            **state,
            "final_reply": response.text,
            "agent_results": {agent.name: response.text},
        }

    return node


debug_agent_node = with_execution_logging(debug_agent_node, "debug", get_default_adapter())
notes_agent_node = with_execution_logging(notes_agent_node, "notes", get_default_adapter())
memory_agent_node = with_execution_logging(memory_agent_node, "memory", get_default_adapter())
normal_agent_node = with_execution_logging(normal_agent_node, "normal", get_default_adapter())

from agents.fix.node import fix_agent_node
from agents.patch.node import patch_apply_node, patch_generate_node
from agents.test.node import test_runner_node
from agents.commit.node import commit_node
from agents.deploy.node import deploy_node

fix_agent_node = with_execution_logging(fix_agent_node, "fix", get_default_adapter())
patch_generate_node = with_execution_logging(patch_generate_node, "patch_generate", get_default_adapter())
patch_apply_node = with_execution_logging(patch_apply_node, "patch_apply", get_default_adapter())
test_runner_node = with_execution_logging(test_runner_node, "test", get_default_adapter())
commit_node = with_execution_logging(commit_node, "commit", get_default_adapter())
deploy_node = with_execution_logging(deploy_node, "deploy", get_default_adapter())


def fallback_node(state: AgentState) -> AgentState:
    results = dict(state.get("agent_results", {}))
    results["fallback"] = "この機能はLangGraphでは未対応です。"
    return {**state, "agent_results": results}


def finalize_node(state: AgentState) -> AgentState:
    results = state.get("agent_results", {})

    print("===== FINALIZER =====")
    print("agent_results =", results)

    if not results:
        reply = "対応できません"
    elif "fallback" in results:
        reply = results.get("fallback", "対応できません")
    else:
        lines = []

        for key, label in (
            ("debug", "Debug"),
            ("notes", "Notes"),
            ("memory", "Memory"),
            ("weather", "Weather"),
            ("english_learning", "English"),
            ("stocks", "Stocks"),
            ("ai_news", "AI NEWS"),
            ("voice", "Voice"),
            ("app_development", "App Development"),
            ("github", "GitHub"),
        ):
            result = results.get(key)
            if result:
                if isinstance(result, dict):
                    text = result.get("text") or result.get("summary") or str(result)
                else:
                    text = str(result)
                lines.append(f"【{label}】\n{text}" if label != "Voice" and label != "English" and label != "Stocks" and label != "AI NEWS" else text)

        for key, label in (
            ("fix", "Fix"),
            ("patch", "Patch"),
            ("test", "Test"),
            ("commit", "Commit"),
            ("deploy", "Deploy"),
        ):
            result = results.get(key)
            if result:
                lines.append(f"【{label}】\n{result if not isinstance(result, dict) else result.get('summary', result.get('text', str(result)))}")

        reply = "\n\n".join(lines) if lines else "対応できません"

    return {**state, "final_reply": reply}


def route_from_debug(state: AgentState) -> str:
    try:
        has_traceback = state["agent_results"]["debug"]["structured"]["error_info"]["has_traceback"]
    except (KeyError, TypeError):
        return "finalizer"
    return "fix_agent" if has_traceback is True else "finalizer"


def build_graph():
    builder = StateGraph(AgentState)
    core_registry = build_core_agent_registry()

    def route_with_core_registry(state: AgentState) -> str:
        return route_from_supervisor(state, core_registry)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("app_development_agent", app_development_agent_node)
    builder.add_node("debug_agent", debug_agent_node)
    builder.add_node("notes_agent", notes_agent_node)
    builder.add_node("memory_agent", memory_agent_node)
    builder.add_node("normal_agent", normal_agent_node)
    builder.add_node("github_agent", github_agent_node)
    builder.add_node("sheets_agent", sheets_agent_node)
    builder.add_node("weather_agent", weather_agent_node)
    builder.add_node("english_learning_agent", english_learning_agent_node)
    builder.add_node("stocks_agent", _agent_node(stocks_agent))
    builder.add_node("ai_news_agent", _agent_node(ai_news_agent))
    builder.add_node("voice_agent", _agent_node(voice_agent))

    builder.add_node("fix_agent", fix_agent_node)
    builder.add_node("patch_generate_agent", patch_generate_node)
    builder.add_node("patch_agent", patch_apply_node)
    builder.add_node("test_agent", test_runner_node)
    builder.add_node("commit_agent", commit_node)
    builder.add_node("deploy_agent", deploy_node)
    builder.add_node("fallback_agent", fallback_node)
    builder.add_node("finalizer", finalize_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_with_core_registry,
        {
            "app_development_agent": "app_development_agent",
            "debug_agent": "debug_agent",
            "notes_agent": "notes_agent",
            "memory_agent": "memory_agent",
            "github_agent": "github_agent",
            "sheets_agent": "sheets_agent",
            "normal_agent": "normal_agent",
            "weather_agent": "weather_agent",
            "english_learning_agent": "english_learning_agent",
            "stocks_agent": "stocks_agent",
            "ai_news_agent": "ai_news_agent",
            "voice_agent": "voice_agent",
            "fallback_agent": "fallback_agent",
        },
    )

    builder.add_conditional_edges("debug_agent", route_from_debug, {"fix_agent": "fix_agent", "finalizer": "finalizer"})

    for node in (
        "app_development_agent",
        "notes_agent",
        "memory_agent",
        "normal_agent",
        "github_agent",
        "sheets_agent",
        "weather_agent",
        "english_learning_agent",
        "stocks_agent",
        "ai_news_agent",
        "voice_agent",
    ):
        builder.add_edge(node, "finalizer")

    builder.add_edge("fix_agent", "patch_generate_agent")
    builder.add_edge("patch_generate_agent", "patch_agent")
    builder.add_edge("patch_agent", "test_agent")
    builder.add_edge("test_agent", "commit_agent")
    builder.add_edge("commit_agent", "deploy_agent")
    builder.add_edge("deploy_agent", "finalizer")
    builder.add_edge("fallback_agent", "finalizer")
    builder.add_edge("finalizer", END)

    return builder.compile()


graph = build_graph()

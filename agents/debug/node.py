"""
LangGraph Phase1: Debug Agent Adapter

注意:
このファイルはLangGraph用のアダプターです。

実際の解析処理:
    agents.debug.collector.collect_error()
    agents.debug.analyzer.analyze_error()
    agents.debug.fixer.generate_fix_suggestion()

を順に呼び出して結果を組み立てます。

既存:
    debug_agent/

のread_only設計とは独立しており、このAdapterからは呼び出しません。
"""


from agents.debug.collector import collect_error
from agents.debug.analyzer import analyze_error
from agents.debug.fixer import generate_fix_suggestion
from graph.state import AgentState


def _strip_debug_prefix(message: str) -> str:
    """
    debug xxx の xxx 部分だけ取り出す
    """

    text = message or ""

    if text.startswith("debug"):
        return text.replace("debug", "", 1).strip()

    return text.strip()


def debug_agent_node(state: AgentState) -> AgentState:
    """
    LangGraph Debug Agentノード
    """

    message = state.get("raw_message", "")

    error_text = _strip_debug_prefix(message)

    try:
        collected = collect_error(error_text)

        analysis = analyze_error(collected)

        fix = generate_fix_suggestion(collected)

        structured_result = {
            "error_info": collected,
            "analysis": analysis,
            "fix": fix,
        }

    except Exception as e:
        structured_result = {
            "error": str(e)
        }

        analysis = ""
        fix = ""


    agent_results = dict(
        state.get("agent_results", {})
    )

    agent_results["debug"] = {
        "text": analysis + "\n\n" + fix,
        "structured": structured_result,
    }

    return {
        **state,
        "agent_results": agent_results,
    }
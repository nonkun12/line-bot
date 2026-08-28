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
from render_client import get_render_logs


# collectorのrawログは解析中だけ使い、LangGraph stateへは渡さない。
# stateはFinalizerやapp.pyのデバッグ出力経由で標準出力に出るため、
# traceback解析・Fix経路に必要な構造化フィールドだけを保持する。
_STATE_ERROR_INFO_FIELDS = (
    "error_type",
    "file",
    "line",
    "message",
    "key",
    "file_hint",
    "source",
    "has_traceback",
    "log_fetch_error",
    "render_log_fetched",
)


def _strip_debug_prefix(message: str) -> str:
    """
    debug xxx の xxx 部分だけ取り出す
    """

    text = message or ""

    if text.startswith("debug"):
        return text.replace("debug", "", 1).strip()

    return text.strip()


def _fetch_render_logs() -> tuple[str | None, str | None]:
    """Renderログを安全に取得し、失敗理由をログ本文と分離して返す。"""

    try:
        logs = get_render_logs()
    except Exception as exc:
        return None, f"Renderログ取得に失敗しました: {type(exc).__name__}"

    # render_client.pyの既存仕様では、APIキー未設定を例外ではなく文字列で返す。
    # これをログとしてcollectorへ渡すと誤解析するため、失敗として正規化する。
    if isinstance(logs, str) and logs.strip() == "RENDER_API_KEY が設定されていません":
        return None, logs.strip()

    if not isinstance(logs, str):
        return None, "Renderログの取得結果が不正です"

    return logs, None


def debug_agent_node(state: AgentState) -> AgentState:
    """
    LangGraph Debug Agentノード
    """

    message = state.get("raw_message", "")

    error_text = _strip_debug_prefix(message)
    render_logs, log_fetch_error = _fetch_render_logs()

    try:
        collected = collect_error(error_text, log_text=render_logs)
        collected["log_fetch_error"] = log_fetch_error
        collected["render_log_fetched"] = render_logs is not None

        analysis = analyze_error(collected)

        fix = generate_fix_suggestion(collected)

        state_error_info = {
            field: collected.get(field)
            for field in _STATE_ERROR_INFO_FIELDS
        }

        structured_result = {
            "error_info": state_error_info,
            "analysis": analysis,
            "fix": fix,
            "log_source": collected.get("source"),
            "log_fetch_error": log_fetch_error,
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

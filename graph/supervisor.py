"""
LangGraph Phase1: Supervisorノード。

責務:
- raw_message からintentを判定する
- next_agent を決定する

やらないこと:
- Agentの実行
- LINE返信生成
"""

from app_development import extract_app_development_request
from graph.state import AgentState
from pending_approvals import PendingStatus, get_pending_status
from agents.notes.intents import is_note_intent
from agents.memory.intents import is_memory_intent
from agents.github.intents import is_github_intent
from agents.sheets.intents import is_sheets_intent
from agents.debug.intents import is_debug_intent
from agents.weather.intents import is_weather_intent
from agents.english.intents import is_english_learning_intent

_DEBUG_PREFIX = "debug"


def _is_english_learning(text: str) -> bool:
    return is_english_learning_intent(text)


def _is_stock_request(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("株", "株価", "銘柄", "ticker", "stock", "stocks", "share price"))


def _is_ai_news_request(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("ai news", "aiニュース", "ai ニュース", "人工知能ニュース"))


def _is_voice_request(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("音声", "ボイス", "aiスピーカー", "voice", "speaker", "しゃべって"))


def classify_intent(raw_message: str, user_id: str | None = None) -> str:
    """メッセージ内容からintentを判定する。"""
    text = (raw_message or "").strip()
    print("===== SUPERVISOR =====")
    print("RAW:", text)

    if text.startswith(_DEBUG_PREFIX):
        return "debug"
    if extract_app_development_request(text) is not None:
        print("SUPERVISOR: app development intent")
        return "app_development"
    if _is_ai_news_request(text):
        return "ai_news"
    if _is_stock_request(text):
        return "stocks"
    if _is_english_learning(text):
        return "english_learning"
    if _is_voice_request(text):
        return "voice"
    if is_sheets_intent(text):
        return "sheets"
    if is_note_intent(text, user_id=user_id):
        return "note"
    if is_github_intent(text):
        return "github"
    if is_weather_intent(text):
        return "weather"
    if is_memory_intent(text):
        return "memory"
    if is_debug_intent(text):
        return "debug"
    return "unsupported"


def supervisor_node(state: AgentState) -> AgentState:
    raw_message = state.get("raw_message", "")
    user_id = state.get("user_id")
    intent = classify_intent(raw_message, user_id=user_id)
    next_agent = {
        "debug": "debug", "app_development": "app_development", "note": "notes",
        "memory": "memory", "github": "github", "sheets": "sheets", "weather": "weather",
        "english_learning": "english_learning", "stocks": "stocks", "ai_news": "ai_news",
        "voice": "voice", "unsupported": "normal",
    }.get(intent, "fallback")
    pending_status = get_pending_status(user_id).value if user_id is not None else PendingStatus.NONE.value
    return {**state, "intent": intent, "next_agent": next_agent, "pending_status": pending_status}

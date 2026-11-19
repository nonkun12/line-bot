"""
Weather Agent intent detection.
"""

import re


_WEATHER_INTENT_RE = re.compile(
    r"(天気|天候|気温|温度|降水確率|雨|雪|晴れ|曇り|"
    r"weather|temperature|forecast)",
    re.IGNORECASE,
)


def is_weather_intent(message: str) -> bool:
    """Return True when the message is asking about weather."""
    text = (message or "").strip()
    if not text:
        return False
    return bool(_WEATHER_INTENT_RE.search(text))

import os


_DEV_NOTES_ENV_KEY = "DEV_NOTES_LOGGING_ENABLED"


def _parse_bool(value: str) -> bool:
    """
    Parse a boolean-like string.

    Accepts: "1", "true", "yes", "on".
    Anything else is treated as False.
    """
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_logging_enabled() -> bool:
    """
    Returns whether development notes logging is enabled.

    Default: False.
    Controlled via DEV_NOTES_LOGGING_ENABLED.
    """
    raw = os.getenv(_DEV_NOTES_ENV_KEY, "").strip()

    if not raw:
        return False

    return _parse_bool(raw)

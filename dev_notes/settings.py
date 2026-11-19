import os


_DEV_NOTES_ENV_KEY = "ENABLE_EXECUTION_LOGGING"


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

    Default: False (safe-by-default).
    Controlled via ENABLE_EXECUTION_LOGGING environment variable.

    Valid values for enabled:
    - "1"
    - "true"
    - "yes"
    - "on"

    Anything else (including "false", "0", or missing) disables logging.
    """
    raw = os.getenv(_DEV_NOTES_ENV_KEY, "").strip()

    if not raw:
        return False

    return _parse_bool(raw)

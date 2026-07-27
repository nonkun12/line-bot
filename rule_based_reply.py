import re
import json
import threading
import unicodedata
from datetime import datetime, timezone, timedelta


_pending_delete_confirmation = {}
_pending_confirm_lock = threading.Lock()


def try_rule_based_reply(
    user_id,
    message,
    call_mcp_tool_fn,
    parse_mcp_json_list_fn,
    handle_relative_time_reminder_fn,
    handle_daily_reminder_fn,
    handle_tomorrow_reminder_fn,
    extract_quoted_text_fn,
    ensure_jst_offset_fn,
):
    """
    ルールベース即時応答処理。

    マッチした場合:
        応答文字列を返す

    マッチしない場合:
        Noneを返す

    save_messageはここでは呼ばない。
    """

    # Aブロック移植予定
    return None
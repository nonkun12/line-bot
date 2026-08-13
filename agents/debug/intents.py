"""
Debug Agent intent detection

「debug」プレフィックスを付けずに送られた自然文(例: 「app.pyのエラーを
確認して」)からDebug Agentへのルーティング要求を検出する。

安全設計:
- エラー系キーワードと調査依頼系キーワードの両方が含まれる場合のみ
  True を返す(AND条件)。どちらか一方だけでは反応しない。
  例: 「予定を確認して」(調査系キーワードのみ) -> False
      「今日エラーが出た」(エラー系キーワードのみ、調査依頼なし) -> False
- Supervisor側 (graph/supervisor.py) では、この判定は
  GitHub / Sheets / Notes / Memory の既存判定より後に呼び出すこと。
  既存Agent向けのキーワードが同時に含まれる場合(例:
  「GitHubのapp.pyのエラーを確認して」)は、既存Agentの判定が
  先に確定するため、この関数まで到達しない。
"""

_ERROR_KEYWORDS = [
    "エラー",
    "バグ",
    "例外",
    "traceback",
    "Traceback",
    "exception",
    "Exception",
    "落ちた",
    "動かない",
    "失敗した",
    "クラッシュ",
    "止まった",
]

_INVESTIGATE_KEYWORDS = [
    "確認して",
    "確認したい",
    "調べて",
    "調べたい",
    "調査して",
    "調査したい",
    "見て",
    "チェックして",
    "教えて",
]


def is_debug_intent(raw_message: str) -> bool:
    """
    自然文からDebug Agent向けの依頼かどうかを判定する。

    エラー系キーワードと調査依頼系キーワードの両方が
    含まれている場合のみ True を返す。
    """

    text = (raw_message or "").strip()

    if not text:
        return False

    has_error_word = any(
        keyword in text for keyword in _ERROR_KEYWORDS
    )

    has_investigate_word = any(
        keyword in text for keyword in _INVESTIGATE_KEYWORDS
    )

    return has_error_word and has_investigate_word

"""
Debug Agent intent detection

「debug」プレフィックスを付けずに送られた自然文(例: 「app.pyのエラーを
確認して」「ModuleNotFoundErrorが発生しました。確認して」)から
Debug Agentへのルーティング要求を検出する。

安全設計:
- エラー系キーワードと調査依頼系キーワードの両方が含まれる場合のみ
  True を返す(AND条件)。どちらか一方だけでは反応しない。
  例: 「予定を確認して」(調査系キーワードのみ) -> False
      「今日エラーが出た」(エラー系キーワードのみ、調査依頼なし) -> False
- エラー系キーワードは、日本語の言い回し(「エラー」「バグ」等)に加えて、
  Pythonの例外クラス名(ModuleNotFoundError, TypeError等)も認識する。
  個別の例外名リストに加えて、"Xxxx" + "Error"/"Exception" という
  一般的な命名パターンも正規表現で拾う(未知の例外名にも対応するため)。
- Supervisor側 (graph/supervisor.py) では、この判定は
  GitHub / Sheets / Notes / Memory の既存判定より後に呼び出すこと。
  既存Agent向けのキーワードが同時に含まれる場合(例:
  「GitHubのapp.pyのエラーを確認して」)は、既存Agentの判定が
  先に確定するため、この関数まで到達しない。
"""

import re


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

# 代表的なPython組み込み例外クラス名。
# 下の _PYTHON_EXCEPTION_PATTERN (汎用パターン) で大半はカバーされるが、
# 可読性・意図の明確化のため代表例をここにも明示しておく。
_PYTHON_EXCEPTION_NAMES = [
    "ModuleNotFoundError",
    "TypeError",
    "ValueError",
    "KeyError",
    "AttributeError",
    "NameError",
    "ImportError",
]

# "Xxxx" + "Error" / "Exception" という一般的なPython例外命名パターンを
# 検出する正規表現。ModuleNotFoundError, ZeroDivisionError,
# CustomException のような、上のリストに個別に列挙していない例外名にも
# 対応するための汎用パターン。
#
# 注意: 末尾の境界判定に \b を使わない。
# Pythonのreモジュールは既定でUnicodeの単語文字を扱うため、日本語の
# 文字(「が」「を」等)も \w とみなされ、"ModuleNotFoundErrorが発生"の
# ような、英数字の直後に日本語が続くケースで \b が「境界なし」と
# 判定されてマッチしなくなる問題があった。
# そのため、"直後にASCII英数字が続かない" ことを否定先読みで保証する
# ことで、日本語が続く場合でも正しく検出できるようにしている。
_PYTHON_EXCEPTION_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:Error|Exception)(?![A-Za-z0-9])"
)

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


def _has_error_word(text: str) -> bool:
    """
    日本語のエラー系キーワード、または
    Pythonの例外クラス名らしき表記が含まれているかを判定する。
    """

    if any(keyword in text for keyword in _ERROR_KEYWORDS):
        return True

    if any(keyword in text for keyword in _PYTHON_EXCEPTION_NAMES):
        return True

    return bool(_PYTHON_EXCEPTION_PATTERN.search(text))


def is_debug_intent(raw_message: str) -> bool:
    """
    自然文からDebug Agent向けの依頼かどうかを判定する。

    エラー系キーワード(日本語表現 or Python例外クラス名)と
    調査依頼系キーワードの両方が含まれている場合のみ True を返す。
    """

    text = (raw_message or "").strip()

    if not text:
        return False

    has_error_word = _has_error_word(text)

    has_investigate_word = any(
        keyword in text for keyword in _INVESTIGATE_KEYWORDS
    )

    return has_error_word and has_investigate_word

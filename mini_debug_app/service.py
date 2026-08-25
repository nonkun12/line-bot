"""
mini_debug_app: 独立DEBUG TOOL サービス層

agents/debug/collector.py, analyzer.py, fixer.py を直接呼び出す。

注意:
- 本番LangGraph Debug Agent (agents/debug/node.py) とは独立しており、
  Renderログ取得やLangGraph state操作は一切行わない。
- ここから agents/debug/ 配下の実装を変更することはない
  (読み取り専用で再利用するのみ)。
- patch生成・適用・commit・deployは行わない。あくまで
  「エラー情報を受け取る -> 解析 -> 修正案生成 -> 結果を返す」までが範囲。
"""

from agents.debug.collector import collect_error
from agents.debug.analyzer import analyze_error
from agents.debug.fixer import generate_fix_suggestion


async def debug_error(error_content: str) -> dict:
    """
    独立DEBUG TOOLのメイン処理。

    collector -> analyzer -> fixer の順に処理し、結果をまとめて返す。
    各ステップで例外が発生した場合は、どのステップで失敗したかが
    わかるメッセージを付けて RuntimeError として送出する
    (呼び出し元のAPI層でHTTPエラーへ変換する)。
    """

    try:
        error_info = collect_error(error_content)
    except Exception as e:
        raise RuntimeError(f"error collection failed: {e}") from e

    try:
        analysis = analyze_error(error_info)
    except Exception as e:
        raise RuntimeError(f"error analysis failed: {e}") from e

    try:
        fix_suggestion = generate_fix_suggestion(error_info)
    except Exception as e:
        raise RuntimeError(f"fix suggestion generation failed: {e}") from e

    return {
        "error_info": error_info,
        "analysis": analysis,
        "fix_suggestion": fix_suggestion,
    }

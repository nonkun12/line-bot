"""
mini_debug_app: 独立DEBUG TOOL API

本番LangGraph Debug Agent (agents/debug/, graph/) や
Graph経由版エントリーポイント (mini_debug_app/app.py) とは独立した、
単体のDEBUG TOOLエンドポイント。

処理フロー:
    POST /debug/ {"error_content": "..."}
        -> mini_debug_app.service.debug_error()
        -> agents.debug.collector / analyzer / fixer を順に呼び出す
        -> {"error_analysis": {"error_info", "analysis", "fix_suggestion"}}

patchの生成・適用・commit・deployは行わない
(agents/patch/, agents/commit/, agents/deploy/ は使用しない)。
"""

from fastapi import FastAPI, HTTPException

from mini_debug_app.schemas import DebugResponse, ErrorInput
from mini_debug_app.service import debug_error


app = FastAPI(title="Mini Debug Tool")


@app.post("/debug/", response_model=DebugResponse)
async def debug(error: ErrorInput):

    try:
        result = await debug_error(error.error_content)
        return {
            "error_analysis": result
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

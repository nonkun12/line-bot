from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mini_debug_app.service import debug_error


app = FastAPI()


class ErrorInput(BaseModel):
    error_content: str


@app.post("/debug/")
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

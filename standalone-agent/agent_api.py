from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from graph.graph import graph
from mcp_client import call_mcp_tool


app = FastAPI()


class AgentRequest(BaseModel):
    message: str
    user_id: str


_DIRECT_TEXT_AGENT_KEYS = ("memory", "notes", "normal", "sheets")


def _extract_reply(result):
    if result is None:
        return None

    agent_results = result.get("agent_results", {}) or {}

    for key in _DIRECT_TEXT_AGENT_KEYS:
        agent_result = agent_results.get(key)
        if isinstance(agent_result, dict):
            text = agent_result.get("text")
            if text:
                return text

    final_reply = result.get("final_reply")
    if final_reply:
        return final_reply

    return None


@app.post("/agent")
def agent(request: AgentRequest):
    result = graph.invoke(
        {
            "user_id": request.user_id,
            "raw_message": request.message,
            "call_mcp_tool": call_mcp_tool,
            "agent_results": {},
        }
    )

    reply = _extract_reply(result)

    if not reply:
        raise HTTPException(
            status_code=500,
            detail="agent response is empty",
        )

    return {"reply": reply}

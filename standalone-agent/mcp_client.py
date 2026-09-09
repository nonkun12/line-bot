import json
import uuid
import httpx

from config import MCP_SERVER_URL, MCP_API_KEY


def call_mcp_tool(tool_name, arguments, timeout=3.0):
    """
    my-mcp-server の /mcp エンドポイントへ JSON-RPC で tools/call を送る。
    StreamableHTTPServerTransport はレスポンスを
    application/json または text/event-stream のどちらでも返し得るため両方に対応する。
    """
    print(f"[LOG] call_mcp_tool called: tool_name={tool_name}")

    print("MCP CALL:", tool_name, arguments)
    print("MCP URL:", MCP_SERVER_URL)

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-api-key": MCP_API_KEY,
        "Connection": "close"
    }

    import time
    print("BEFORE MCP REQUEST")
    print("TIMEOUT:", timeout)
    print("POST START TIME:", time.time())
    try:
        print("REQUEST START")
        print("MCP BEFORE REQUESTS POST")
        print("BEFORE POST CALL", time.time())
        res = httpx.post(
            MCP_SERVER_URL,
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=False,
        )
        print("MCP AFTER REQUESTS POST")
        print("MCP RESPONSE STATUS:", res.status_code)
        print("MCP CONTENT TYPE:", res.headers.get("content-type"))
        print("RESPONSE OBJECT:", res)
    except Exception as e:
        import traceback
        print("EXCEPTION TYPE:", type(e))
        traceback.print_exc()
        raise
    print("REQUEST END")
    print("AFTER MCP REQUEST")
    print("POST END TIME:", time.time())

    print("MCP STATUS:", res.status_code)
    print("MCP HEADERS:", res.headers)

    res.raise_for_status()

    content_type = res.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        body = None
        try:
            for line in res.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data:"):
                        data_line = decoded_line[len("data:"):].strip()
                        body = json.loads(data_line)
                        break
        finally:
            res.close()

        if body is None:
            raise RuntimeError("MCP SSEレスポンスにdataが見つかりません")
    else:
        try:
            body = res.json()
        finally:
            res.close()

    print("MCP PARSED BODY:", body)

    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")

    result = body.get("result", {})
    parts = result.get("content", [])
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(texts) if texts else ""


def parse_mcp_json_list(raw):
    print(f"[LOG] _parse_mcp_json_list called")

    if not raw:
        return []

    if isinstance(raw, list):
        return raw

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            content = (
                data.get("result", {})
                .get("content", [])
            )

            if content and isinstance(content[0], dict):
                text = content[0].get("text", "")

                try:
                    parsed = json.loads(text)
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    return []

        return data if isinstance(data, list) else []

    except Exception as e:
        print("parse error:", e)
        return []

"""Normal Agent package bootstrap.

Bind the Wikipedia tool into the existing Groq function-calling tool registry
without changing the Normal Agent implementation itself.
"""

from bot_tools import MCP_TOOLS_SCHEMA as _MCP_TOOLS_SCHEMA
import bot_tools as _bot_tools
from wikipedia_tool import WIKIPEDIA_TOOL_SCHEMA, wikipedia_search


if not any(
    item.get("function", {}).get("name") == "wikipedia_search"
    for item in _MCP_TOOLS_SCHEMA
):
    _MCP_TOOLS_SCHEMA.append(WIKIPEDIA_TOOL_SCHEMA)


_original_dispatch_tool_call = _bot_tools.dispatch_tool_call


def _dispatch_tool_call_with_wikipedia(user_id, name, arguments, original_message=""):
    if name == "wikipedia_search":
        try:
            print(f"[LOG] wikipedia_search called: query={arguments.get('query', '')!r}")
            return wikipedia_search(arguments.get("query", ""))
        except Exception as exc:
            print("WIKIPEDIA TOOL ERROR:", exc)
            return "Wikipedia検索中にエラーが発生しました。"

    return _original_dispatch_tool_call(
        user_id,
        name,
        arguments,
        original_message=original_message,
    )


if getattr(_bot_tools.dispatch_tool_call, "__name__", "") != "_dispatch_tool_call_with_wikipedia":
    _bot_tools.dispatch_tool_call = _dispatch_tool_call_with_wikipedia

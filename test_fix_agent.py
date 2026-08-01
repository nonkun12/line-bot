from dotenv import load_dotenv

load_dotenv()

from graph.graph import graph


def test_fix_agent():
    state = {
        "raw_message": """debug
Traceback (most recent call last):
  File "app.py", line 120
KeyError: user_id
""",
        "agent_results": {},
    }

    result = graph.invoke(state)

    fix = (
        result
        .get("agent_results", {})
        .get("fix")
    )

    assert fix is not None

    patch = fix.get("patch", "")

    assert isinstance(patch, str)

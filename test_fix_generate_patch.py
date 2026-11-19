from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from graph.graph import graph


def test_fix_generate_patch():
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
        .get("fix", {})
    )

    patch = fix.get(
        "patch",
        ""
    )

    assert isinstance(patch, str)

    Path(
        "fix_generated.patch"
    ).write_text(
        patch
    )

    assert Path("fix_generated.patch").exists()

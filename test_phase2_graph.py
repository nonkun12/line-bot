from graph.graph import graph


def test_phase2_graph():
    state = {
        "user_id": "test-user",
        "raw_message": """debug
Traceback (most recent call last):
  File "app.py", line 120
KeyError: user_id
""",
        "agent_results": {},
    }

    result = graph.invoke(state)

    assert result is not None

    assert "agent_results" in result

    assert result.get("final_reply") is not None

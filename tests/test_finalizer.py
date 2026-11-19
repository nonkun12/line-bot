from graph.graph import finalize_node


def test_finalizer_with_full_result():

    state = {
        "agent_results": {
            "debug": {
                "text": "KeyError detected"
            },
            "fix": {
                "summary": "change data access"
            },
            "patch": {
                "applied": False,
                "skipped": True,
            },
            "test": {
                "passed": None,
                "skipped": True,
            },
            "commit": {
                "committed": False,
                "skipped": True,
            },
            "deploy": {
                "pending": True,
            },
        }
    }

    result = finalize_node(state)

    assert "KeyError detected" in result["final_reply"]
    assert "change data access" in result["final_reply"]


def test_finalizer_fallback():

    state = {
        "agent_results": {
            "fallback": "unsupported"
        }
    }

    result = finalize_node(state)

    assert result["final_reply"] == "unsupported"

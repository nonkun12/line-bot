from graph.graph import graph


def test_phase2_graph(monkeypatch):
    monkeypatch.setattr(
        "agents.debug.node.get_render_logs",
        lambda: "",
    )

    state = {
        "user_id": "test-user",
        "raw_message": "app.pyのエラーを確認して",
        "agent_results": {},
    }

    result = graph.invoke(state)

    assert result is not None

    assert "agent_results" in result

    assert result.get("final_reply") is not None
    assert "debug" in result["agent_results"]
    assert "fix" not in result["agent_results"]
    assert "patch" not in result["agent_results"]
    assert "test" not in result["agent_results"]
    assert "commit" not in result["agent_results"]
    assert "deploy" not in result["agent_results"]

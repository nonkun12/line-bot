from agents.english import agent


def test_english_agent_export_is_available():
    assert agent.name == "english"
    assert agent.enabled is True

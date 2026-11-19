from agents.english import EnglishLearningAgent, agent


def test_english_module_exports_agent():
    assert isinstance(agent, EnglishLearningAgent)
    assert agent.name == "english"

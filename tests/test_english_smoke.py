def test_english_foundation_imports():
    from agents.english_agent import EnglishLearningAgent
    assert EnglishLearningAgent().name == "english"

from agents.jobs.intents import classify_job_mode, is_job_seeking_intent
from agents.jobs.node import JobSeekingAgent
from core.agents import AgentRequest


def test_job_intents_and_modes():
    assert is_job_seeking_intent("求人を探したい")
    assert classify_job_mode("履歴書を作りたい") == "resume"
    assert classify_job_mode("面接対策をしたい") == "interview"


def test_agent_never_claims_real_listings():
    response = JobSeekingAgent().handle(AgentRequest("u", "求人を探したい", channel="slack"))
    assert response.metadata["feature"] == "job_seeking"
    assert response.metadata["mode"] == "search"
    assert "外部求人サイト" in response.text
    assert "生成することはしません" in response.text


def test_agent_exposes_document_mode():
    response = JobSeekingAgent().handle(AgentRequest("u", "履歴書を作りたい"))
    assert response.metadata["mode"] == "resume"
    assert "職歴" in response.text

from agents.jobs.intents import extract_job_search_criteria
from agents.jobs.node import JobSeekingAgent
from agents.jobs.search_contract import JobListing, JobSearchResult
from core.agents import AgentRequest


def test_job_search_criteria_parses_only_explicit_constraints():
    criteria = extract_job_search_criteria(
        "求人 職種: Pythonエンジニア、勤務地: 東京、年収下限: 600万円、"
        "フルリモート、必須スキル: Python, AWS"
    )
    assert criteria.occupation == "Pythonエンジニア"
    assert criteria.location == "東京"
    assert criteria.salary_min_yen == 6_000_000
    assert criteria.remote == "full_remote"
    assert criteria.skills == ("Python", "AWS")


def test_job_search_criteria_does_not_guess_unlabelled_values():
    criteria = extract_job_search_criteria("東京でPython、年収600万円の求人")
    assert criteria.occupation is None
    assert criteria.location is None
    assert criteria.salary_min_yen == 6_000_000
    assert criteria.remote is None
    assert criteria.skills == ()


def test_default_job_search_never_fabricates_listings():
    agent = JobSeekingAgent()
    response = agent.handle(
        AgentRequest("u1", "求人 職種: Pythonエンジニア")
    )
    assert "存在しない求人は生成しません" in response.text
    assert response.metadata["search_status"] == "unavailable"
    assert response.metadata["result_count"] == 0


def test_job_search_provider_results_are_source_backed():
    class Provider:
        def search(self, criteria):
            assert criteria.occupation == "Pythonエンジニア"
            return JobSearchResult(
                status="ok",
                listings=(
                    JobListing(
                        title="Python Engineer",
                        company="Example",
                        location="Tokyo",
                        url="https://example.com/jobs/1",
                        source="example",
                    ),
                ),
            )

    response = JobSeekingAgent(Provider()).handle(
        AgentRequest("u1", "求人 職種: Pythonエンジニア")
    )
    assert "Python Engineer" in response.text
    assert "https://example.com/jobs/1" in response.text
    assert response.metadata["result_count"] == 1


def test_job_listing_rejects_untrusted_shape():
    from agents.jobs.search_contract import JobListing
    import pytest

    with pytest.raises(ValueError):
        JobListing("", "Example", "Tokyo", "https://example.com/1", "example")
    with pytest.raises(ValueError):
        JobListing("Job", "Example", "Tokyo", "javascript:alert(1)", "example")


def test_invalid_provider_response_fails_closed():
    class Provider:
        def search(self, criteria):
            return object()

    agent = JobSeekingAgent(Provider())
    response = agent.handle(AgentRequest("u1", "求人 職種: Pythonエンジニア"))
    assert response.metadata["search_status"] == "error"
    assert response.metadata["result_count"] == 0

def _handoff() -> ApprovedImprovementHandoff:
    task = AgentTask(
        "self-improvement:test",
        AgentRole.DEBUGGER,
        "Investigate recurring failure.",
        frozenset({"runtime"}),
    )
    return ApprovedImprovementHandoff(
        task=task,
        task_hash=task_hash(task) or "",
        allowed_paths=("tests/test_agent_runtime.py",),
    )


def test_handoff_claim_store_is_one_time(tmp_path):
    store = ApprovedImprovementHandoffClaimStore(tmp_path / "claims.jsonl")
    handoff = _handoff()
    assert store.claim(handoff) is True
    assert store.claim(handoff) is False
    assert store.is_claimed(handoff) is True


def test_handoff_claim_store_rejects_invalid_handoff(tmp_path):
    store = ApprovedImprovementHandoffClaimStore(tmp_path / "claims.jsonl")
    task = AgentTask("self-improvement:test", AgentRole.IMPLEMENTER, "unsafe")
    invalid = ApprovedImprovementHandoff(task=task, task_hash=task_hash(task) or "", allowed_paths=("tests/test_agent_runtime.py",))
    import pytest
    with pytest.raises(PermissionError):
        store.claim(invalid)


def test_handoff_claim_store_ignores_tampered_claim_records(tmp_path):
    path = tmp_path / "claims.jsonl"
    path.write_text('1234\n"bad"\n', encoding="utf-8")
    store = ApprovedImprovementHandoffClaimStore(path)
    assert store._read() == ["bad"] or store._read() == []

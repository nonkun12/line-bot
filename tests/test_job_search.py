from core.job_search import JobPosting, JobSearchCriteria, score_job, rank_jobs


def test_score_job_uses_only_explicit_criteria():
    criteria = JobSearchCriteria(
        keywords=("Python",),
        locations=("東京",),
        min_salary=600,
        remote_ok=True,
        required_skills=("Python", "AWS"),
    )
    posting = JobPosting(
        job_id="j1", title="Python Engineer", company="Acme", location="東京",
        salary_min=650, salary_max=800, remote=True, skills=("Python", "AWS"),
    )
    score = score_job(posting, criteria)
    assert score.total == 1.0
    assert score.skill_match == 1.0
    assert "必須スキルをすべて確認" in score.reasons


def test_rank_jobs_is_deterministic():
    criteria = JobSearchCriteria(keywords=("Python",))
    postings = (
        JobPosting("b", "Python Engineer", "B"),
        JobPosting("a", "Python Engineer", "A"),
    )
    scores = rank_jobs(postings, criteria)
    assert [item.job_id for item in scores] == ["a", "b"]


class Provider:
    def search(self, criteria, limit=20):
        return [
            JobPosting("j2", "Other", "B", location="東京"),
            JobPosting("j1", "Python Engineer", "A", location="東京"),
        ]


def test_search_and_rank_jobs_uses_provider_results_and_stays_deterministic():
    from core.job_search import search_and_rank_jobs

    result = search_and_rank_jobs(Provider(), JobSearchCriteria(keywords=("Python",)), limit=2)
    assert [item.job_id for item in result] == ["j1", "j2"]


def test_search_and_rank_jobs_fails_closed_on_provider_error():
    class BrokenProvider:
        def search(self, criteria, limit=20):
            raise RuntimeError("unavailable")

    from core.job_search import search_and_rank_jobs
    assert search_and_rank_jobs(BrokenProvider(), JobSearchCriteria()) == ()

import os

from core.local_review_trigger import dispatch_local_review, extract_local_review_pr


BASE = "a" * 40
HEAD = "b" * 40


def test_only_explicit_pr_command_is_recognized():
    assert extract_local_review_pr("ローカルレビュー PR #676") == 676
    assert extract_local_review_pr("ローカルレビュー PR 676") == 676
    assert extract_local_review_pr("PR #676をレビューして") is None
    assert extract_local_review_pr("ローカルレビュー PR #0") is None
    assert extract_local_review_pr("ローカルレビュー PR #676 extra") is None


def test_authorization_fails_closed_when_allowlist_missing(monkeypatch):
    monkeypatch.delenv("LOCAL_REVIEW_ALLOWED_USER_IDS", raising=False)
    called = []
    result = dispatch_local_review("U1", "ローカルレビュー PR #676", get_pr=lambda *args: called.append(args), channel="line")
    assert "許可された利用者" in result
    assert called == []


def test_authorized_request_enqueues_canonical_sha_pair(monkeypatch):
    monkeypatch.setenv("LOCAL_REVIEW_ALLOWED_USER_IDS", "U1,U2")
    captured = {}
    monkeypatch.setattr(
        "core.local_review_trigger.enqueue_local_review",
        lambda user, repo, base, head: captured.update(user=user, repo=repo, base=base, head=head) or 41,
    )
    def fake_get_pr(repo, number, token):
        assert repo == "nonkun12/line-bot"
        assert number == 676
        return {
            "state": "open",
            "merged": False,
            "base": {"sha": BASE, "repo": {"full_name": repo}},
            "head": {"sha": HEAD, "repo": {"full_name": repo}},
        }
    result = dispatch_local_review("U1", "ローカルレビュー PR #676", token="fake", get_pr=fake_get_pr, channel="line")
    assert "Job 41" in result
    assert captured == {"user": "U1", "repo": "nonkun12/line-bot", "base": BASE, "head": HEAD}


def test_rejects_fork_pr(monkeypatch):
    monkeypatch.setenv("LOCAL_REVIEW_ALLOWED_USER_IDS", "U1")
    def fake_get_pr(repo, number, token):
        return {
            "state": "open",
            "base": {"sha": BASE, "repo": {"full_name": repo}},
            "head": {"sha": HEAD, "repo": {"full_name": "attacker/fork"}},
        }
    result = dispatch_local_review("U1", "ローカルレビュー PR #676", get_pr=fake_get_pr)
    assert "許可されていないリポジトリ" in result



def test_rejects_explicit_review_command_from_non_line_channel(monkeypatch):
    monkeypatch.setenv("LOCAL_REVIEW_ALLOWED_USER_IDS", "U1")
    called = []
    result = dispatch_local_review(
        "U1", "ローカルレビュー PR #676", channel="internal",
        get_pr=lambda *args: called.append(args),
    )
    assert "LINEからのみ" in result
    assert called == []

"""Regression tests for GitHub Agent command-vs-prose routing."""

from agents.github.handlers import handle_github_message, handle_github_search


def test_search_does_not_match_embedded_command_phrase():
    message = (
        "Please inspect github repo, github commits, github file app.py, "
        "and github search line-bot as separate commands."
    )

    assert handle_github_search(message) is None


def test_github_message_does_not_execute_commands_mentioned_in_prose(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def search_repositories(self, *args, **kwargs):
            raise AssertionError("prose must not trigger repository search")

        def get_repo_info(self, *args, **kwargs):
            raise AssertionError("prose must not trigger repo lookup")

        def get_latest_commits(self, *args, **kwargs):
            raise AssertionError("prose must not trigger commit lookup")

        def get_file_contents(self, *args, **kwargs):
            raise AssertionError("prose must not trigger file lookup")

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    result = handle_github_message(
        "Please inspect github repo, github commits, github file app.py, "
        "and github search line-bot as separate commands.",
        user_id="test-user",
    )

    assert result == "GitHub Agent: 対応コマンド github repo / commits / file / search です。"


def test_exact_search_command_still_works(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def search_repositories(self, query, count=5):
            assert query == "line bot"
            return {
                "ok": True,
                "items": [{
                    "full_name": "owner/line-bot",
                    "description": "test",
                    "language": "Python",
                    "stargazers_count": 1,
                    "html_url": "https://github.com/owner/line-bot",
                }],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    result = handle_github_message("github search line bot", user_id="test-user")

    assert "owner/line-bot" in result


def test_exact_repo_command_still_works(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_repo_info(self):
            return {
                "full_name": "nonkun12/line-bot",
                "language": "Python",
                "default_branch": "main",
                "stargazers_count": 1,
                "html_url": "https://github.com/nonkun12/line-bot",
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    result = handle_github_message("github repo", user_id="test-user")

    assert "nonkun12/line-bot" in result

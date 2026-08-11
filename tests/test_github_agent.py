from agents.github.node import github_agent_node
from agents.github.intents import (
    is_github_intent,
    is_issue_or_pr_intent,
    is_pull_request_intent,
    is_issue_intent,
)
from agents.github.handlers import (
    handle_latest_commits,
    handle_file_contents,
    handle_github_search,
    handle_issue_or_pr_request,
    handle_github_message,
    format_search_results,
    format_commits,
    format_issues,
    format_pull_requests,
)


def test_github_agent_node_calls_real_commit_api_for_natural_language_request(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_latest_commits(self, count=5):
            return [
                {
                    "sha": "abc1234567",
                    "commit": {"message": "fix: something\n\nlonger body"},
                }
            ]

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    result = github_agent_node(
        {
            "user_id": "user123",
            "raw_message": "GitHubの最新コミットを教えて",
            "agent_results": {},
        }
    )

    text = result["agent_results"]["github"]["text"]

    assert "準備中" not in text
    assert "【Latest Commits】" in text
    assert "abc1234" in text
    assert "fix: something" in text


def test_handle_latest_commits_calls_client_and_formats_result(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_latest_commits(self, count=5):
            return [
                {"sha": "1111111aaaa", "commit": {"message": "first commit"}},
                {"sha": "2222222bbbb", "commit": {"message": "second commit"}},
            ]

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    for message in [
        "最新コミットを教えて",
        "latest commit please",
        "commit historyを見せて",
        "このリポジトリのコミットを見せて",
        "GitHubのコミットを確認して",
    ]:
        text = handle_latest_commits(message)
        assert text is not None
        assert "準備中" not in text
        assert "【Latest Commits】" in text
        assert "first commit" in text


def test_handle_latest_commits_returns_none_for_non_latest_commit_queries():
    assert handle_latest_commits("GitHubについて教えて") is None
    assert handle_latest_commits("今日は天気がいいですね") is None



def test_is_github_intent_detects_github_related_queries():
    assert is_github_intent("GitHubの最新コミットを教えて")
    assert is_github_intent("最新のPRを表示して")
    assert is_github_intent("issueを確認したい")
    assert is_github_intent("リポジトリのファイル内容を見せて")
    assert is_github_intent("commit historyを教えて")


def test_is_github_intent_returns_false_for_non_github_messages():
    assert not is_github_intent("今日は天気がいいですね")
    assert not is_github_intent("メモを保存して")
    assert not is_github_intent("明日のリマインダーを設定して")


def test_is_github_intent_detects_natural_language_file_content_requests():
    """
    Regression test: is_github_intent() must recognize the same
    natural-language file content phrasing that handle_file_contents()
    already handles (e.g. "README.mdを見せて"), so these requests are
    routed to the GitHub Agent instead of falling through to the Normal
    Agent.
    """
    assert is_github_intent("README.mdを見せて")
    assert is_github_intent("README.mdの内容を見せて")
    assert is_github_intent("README.mdを表示して")
    assert is_github_intent("app.pyを表示して")
    assert is_github_intent("github file README.md")


def test_is_github_intent_returns_false_for_unrelated_readme_questions():
    assert not is_github_intent("READMEの書き方を教えて")
    assert not is_github_intent("READMEって何ですか？")


# ---------------------------------------------------------------------------
# GitHub Search result formatting (Phase3-4)
# ---------------------------------------------------------------------------

def _make_repo_item(
    full_name="octocat/Hello-World",
    description="My first repository",
    language="Python",
    stars=42,
    url="https://github.com/octocat/Hello-World",
):
    return {
        "full_name": full_name,
        "description": description,
        "language": language,
        "stargazers_count": stars,
        "html_url": url,
    }


def test_format_search_results_single_result_dict_shape():
    result = {
        "ok": True,
        "items": [_make_repo_item()],
        "error": None,
        "status": 200,
    }

    text = format_search_results(result)

    assert "【GitHub Search Results】" in text
    assert "octocat/Hello-World" in text
    assert "Python" in text
    assert "⭐ Stars: 42" in text
    assert "https://github.com/octocat/Hello-World" in text


def test_format_search_results_multiple_results():
    result = {
        "ok": True,
        "items": [
            _make_repo_item(full_name="owner/repo1", stars=100),
            _make_repo_item(full_name="owner/repo2", stars=45),
        ],
        "error": None,
        "status": 200,
    }

    text = format_search_results(result)

    assert "1. 📦 owner/repo1" in text
    assert "2. 📦 owner/repo2" in text
    assert "⭐ Stars: 100" in text
    assert "⭐ Stars: 45" in text


def test_format_search_results_zero_results():
    result = {"ok": True, "items": [], "error": None, "status": 200}

    text = format_search_results(result)

    assert text == "GitHub検索結果が見つかりませんでした。"


def test_format_search_results_accepts_legacy_bare_list_shape():
    # Defensive support for the pre-Phase3-4 shape where the client
    # returned a bare list of items instead of a dict envelope.
    items = [_make_repo_item(full_name="owner/legacy-repo")]

    text = format_search_results(items)

    assert "owner/legacy-repo" in text


def test_format_search_results_handles_dict_with_raw_items_key():
    # Defensive support for a raw {"items": [...]} dict (e.g. the raw
    # GitHub API response passed straight through).
    result = {"items": [_make_repo_item(full_name="owner/raw-items")]}

    text = format_search_results(result)

    assert "owner/raw-items" in text


def test_format_search_results_api_error_dict_shape():
    result = {
        "ok": False,
        "items": [],
        "error": "GitHub API error",
        "status": 403,
    }

    text = format_search_results(result)

    assert text == "GitHub検索でエラーが発生しました。"


def test_format_search_results_legacy_list_of_error_dicts_is_not_rendered_as_items():
    # This is the historical list/dict bug: an error response shaped as
    # [{"error": ..., "status": ...}] must never be rendered as if it
    # were a search result item.
    result = [{"error": "GitHub API error", "status": 500}]

    text = format_search_results(result)

    assert text == "GitHub検索でエラーが発生しました。"
    assert "None" not in text


def test_format_search_results_none_input_is_treated_as_error():
    text = format_search_results(None)

    assert text == "GitHub検索でエラーが発生しました。"


def test_format_search_results_handles_incomplete_item_data():
    incomplete_item = {"full_name": "owner/incomplete-repo"}
    result = {"ok": True, "items": [incomplete_item], "error": None, "status": 200}

    text = format_search_results(result)

    assert "owner/incomplete-repo" in text
    assert "説明なし" in text
    assert "Language: -" in text
    assert "⭐ Stars: -" in text


def test_format_search_results_limits_to_five_items():
    items = [_make_repo_item(full_name=f"owner/repo{i}") for i in range(10)]
    result = {"ok": True, "items": items, "error": None, "status": 200}

    text = format_search_results(result)

    assert "owner/repo0" in text
    assert "owner/repo4" in text
    assert "owner/repo5" not in text


def test_handle_github_search_uses_client_and_formats_result(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def search_repositories(self, query, count=5):
            assert query == "line bot"
            return {
                "ok": True,
                "items": [_make_repo_item(full_name="owner/line-bot")],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    text = handle_github_search("github search line bot")

    assert text is not None
    assert "owner/line-bot" in text


def test_handle_github_search_returns_none_when_no_query_pattern_matches():
    assert handle_github_search("今日は天気がいいですね") is None


# ---------------------------------------------------------------------------
# GitHubClient.search_repositories contract (Phase3-4)
# ---------------------------------------------------------------------------

from agents.github.client import GitHubClient


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


def test_client_search_repositories_returns_ok_dict_with_items(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(200, {"items": [_make_repo_item()]})

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.search_repositories("hello")

    assert result["ok"] is True
    assert result["error"] is None
    assert len(result["items"]) == 1
    assert result["items"][0]["full_name"] == "octocat/Hello-World"


def test_client_search_repositories_handles_bare_list_response(monkeypatch):
    # Defensive handling in case the API/mocked response is a bare list
    # instead of the usual {"items": [...]} envelope.
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(200, [_make_repo_item(full_name="owner/bare-list")])

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.search_repositories("hello")

    assert result["ok"] is True
    assert result["items"][0]["full_name"] == "owner/bare-list"


def test_client_search_repositories_returns_error_dict_on_non_200(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(403, {"message": "API rate limit exceeded"})

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.search_repositories("hello")

    assert result["ok"] is False
    assert result["items"] == []
    assert result["status"] == 403


def test_client_search_repositories_returns_error_dict_on_exception(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.search_repositories("hello")

    assert result["ok"] is False
    assert result["items"] == []
    assert "network down" in result["error"]


# ---------------------------------------------------------------------------
# GitHubClient.get_issues / get_pull_requests contract (Phase3-5)
# ---------------------------------------------------------------------------

def test_client_get_issues_returns_ok_dict_with_items(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://api.github.com/repos/nonkun12/line-bot/issues"
        return _FakeResponse(200, [_make_issue()])

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy", repo="nonkun12/line-bot")
    result = client.get_issues()

    assert result["ok"] is True
    assert result["error"] is None
    assert result["items"][0]["number"] == 12


def test_client_get_issues_filters_out_pull_requests(monkeypatch):
    # GitHub's /issues endpoint also returns PRs; entries with a
    # "pull_request" key must be excluded from get_issues() results.
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(
            200,
            [
                _make_issue(number=12),
                {**_make_issue(number=25), "pull_request": {"url": "..."}},
            ],
        )

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy", repo="nonkun12/line-bot")
    result = client.get_issues()

    numbers = [item["number"] for item in result["items"]]
    assert numbers == [12]


def test_client_get_issues_returns_error_dict_on_non_200(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy", repo="nonkun12/line-bot")
    result = client.get_issues()

    assert result["ok"] is False
    assert result["items"] == []
    assert result["status"] == 404


def test_client_get_pull_requests_returns_ok_dict_with_items(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://api.github.com/repos/nonkun12/line-bot/pulls"
        return _FakeResponse(200, [_make_pr()])

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy", repo="nonkun12/line-bot")
    result = client.get_pull_requests()

    assert result["ok"] is True
    assert result["error"] is None
    assert result["items"][0]["number"] == 25


def test_client_get_pull_requests_returns_error_dict_on_exception(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy", repo="nonkun12/line-bot")
    result = client.get_pull_requests()

    assert result["ok"] is False
    assert result["items"] == []
    assert "network down" in result["error"]


# ---------------------------------------------------------------------------
# format_commits (Phase3-5)
# ---------------------------------------------------------------------------

def _make_commit(sha="abcdef1234567890", message="fix: bug"):
    return {"sha": sha, "commit": {"message": message}}


def test_format_commits_normal_list():
    commits = [_make_commit(sha="1111111", message="first"), _make_commit(sha="2222222", message="second")]

    text = format_commits(commits)

    assert "【Latest Commits】" in text
    assert "1111111" in text
    assert "first" in text
    assert "second" in text


def test_format_commits_zero_commits():
    assert format_commits([]) == "コミットが見つかりませんでした。"
    assert format_commits({"items": []}) == "コミットが見つかりませんでした。"


def test_format_commits_api_error_list_shape():
    text = format_commits([{"error": "GitHub API error", "status": 500}])

    assert text == "GitHubコミット取得でエラーが発生しました。"
    assert "None" not in text


def test_format_commits_api_error_dict_shape():
    text = format_commits({"error": "GitHub API error", "status": 403})

    assert text == "GitHubコミット取得でエラーが発生しました。"


def test_format_commits_none_input_is_treated_as_error():
    assert format_commits(None) == "GitHubコミット取得でエラーが発生しました。"


def test_format_commits_handles_incomplete_commit_data():
    incomplete_commit = {"sha": "abcdefg"}

    text = format_commits([incomplete_commit])

    assert "abcdefg" in text
    assert "(no message)" in text


def test_format_commits_limits_to_five():
    commits = [_make_commit(sha=f"{i}" * 7, message=f"commit{i}") for i in range(10)]

    text = format_commits(commits)

    assert "commit0" in text
    assert "commit4" in text
    assert "commit5" not in text


# ---------------------------------------------------------------------------
# github commits prefix command still works (Phase3-4 behaviour, unchanged)
# ---------------------------------------------------------------------------

def test_handle_github_message_github_commits_prefix_still_works(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_latest_commits(self, count=5):
            return [_make_commit(sha="deadbee", message="prefix command works")]

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    text = handle_github_message("github commits", user_id="user123")

    assert "prefix command works" in text
    assert "【Latest Commits】" in text


# ---------------------------------------------------------------------------
# Issue / Pull Request intent recognition (Phase3-5)
# ---------------------------------------------------------------------------

def test_is_issue_or_pr_intent_detects_issue_and_pr_queries():
    assert is_issue_or_pr_intent("PRある？")
    assert is_issue_or_pr_intent("Issueを確認して")
    assert is_issue_or_pr_intent("プルリクエストを見せて")
    assert is_issue_or_pr_intent("pull request please")


def test_is_issue_or_pr_intent_returns_false_for_unrelated_messages():
    assert not is_issue_or_pr_intent("今日は天気がいいですね")
    assert not is_issue_or_pr_intent("最新コミットを教えて")


def test_is_pull_request_intent_detects_pr_queries_only():
    assert is_pull_request_intent("PRを見せて")
    assert is_pull_request_intent("Pull Requestを教えて")
    assert is_pull_request_intent("PR一覧を教えて")
    assert is_pull_request_intent("オープン中のPRを教えて")
    assert not is_pull_request_intent("Issueを見せて")
    assert not is_pull_request_intent("今日は天気がいいですね")


def test_is_issue_intent_detects_issue_queries_only():
    assert is_issue_intent("Issueを見せて")
    assert is_issue_intent("Issue一覧を教えて")
    assert is_issue_intent("未解決のIssueを教えて")
    assert is_issue_intent("オープンなIssueを教えて")
    assert not is_issue_intent("PRを見せて")
    assert not is_issue_intent("今日は天気がいいですね")


# ---------------------------------------------------------------------------
# format_issues (Phase3-5)
# ---------------------------------------------------------------------------

def _make_issue(number=12, title="Fix login error", state="open", url="https://github.com/owner/repo/issues/12"):
    return {"number": number, "title": title, "state": state, "html_url": url}


def test_format_issues_normal_list():
    result = {
        "ok": True,
        "items": [
            _make_issue(number=12, title="Fix login error"),
            _make_issue(number=10, title="Update README", state="open"),
        ],
        "error": None,
        "status": 200,
    }

    text = format_issues(result)

    assert "【GitHub Issues】" in text
    assert "#12 Fix login error" in text
    assert "#10 Update README" in text
    assert "open" in text
    assert "https://github.com/owner/repo/issues/12" in text


def test_format_issues_zero_results():
    result = {"ok": True, "items": [], "error": None, "status": 200}

    assert format_issues(result) == "Issueが見つかりませんでした。"


def test_format_issues_error_dict_shape():
    result = {"ok": False, "items": [], "error": "GitHub API error", "status": 403}

    assert format_issues(result) == "GitHub Issue取得でエラーが発生しました。"


def test_format_issues_none_input_is_treated_as_error():
    assert format_issues(None) == "GitHub Issue取得でエラーが発生しました。"


def test_format_issues_limits_to_five():
    items = [_make_issue(number=i, title=f"issue{i}") for i in range(10)]
    result = {"ok": True, "items": items, "error": None, "status": 200}

    text = format_issues(result)

    assert "issue0" in text
    assert "issue4" in text
    assert "issue5" not in text


# ---------------------------------------------------------------------------
# format_pull_requests (Phase3-5)
# ---------------------------------------------------------------------------

def _make_pr(number=25, title="Add GitHub Issue support", state="open", url="https://github.com/owner/repo/pull/25", merged_at=None):
    return {
        "number": number,
        "title": title,
        "state": state,
        "html_url": url,
        "merged_at": merged_at,
    }


def test_format_pull_requests_normal_list():
    result = {
        "ok": True,
        "items": [
            _make_pr(number=25, title="Add GitHub Issue support"),
            _make_pr(number=24, title="Fix search formatting", state="closed", merged_at="2026-01-01T00:00:00Z"),
        ],
        "error": None,
        "status": 200,
    }

    text = format_pull_requests(result)

    assert "【GitHub Pull Requests】" in text
    assert "#25 Add GitHub Issue support" in text
    assert "#24 Fix search formatting" in text
    assert "open" in text
    assert "merged" in text
    assert "https://github.com/owner/repo/pull/25" in text


def test_format_pull_requests_zero_results():
    result = {"ok": True, "items": [], "error": None, "status": 200}

    assert format_pull_requests(result) == "Pull Requestが見つかりませんでした。"


def test_format_pull_requests_error_dict_shape():
    result = {"ok": False, "items": [], "error": "GitHub API error", "status": 500}

    assert format_pull_requests(result) == "GitHub Pull Request取得でエラーが発生しました。"


def test_format_pull_requests_none_input_is_treated_as_error():
    assert format_pull_requests(None) == "GitHub Pull Request取得でエラーが発生しました。"


# ---------------------------------------------------------------------------
# handle_issue_or_pr_request / handle_github_message (Phase3-5, real API)
# ---------------------------------------------------------------------------

def test_handle_issue_or_pr_request_returns_none_for_unrelated_messages():
    assert handle_issue_or_pr_request("今日は天気がいいですね") is None


def test_handle_issue_or_pr_request_fetches_issues_for_issue_queries(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_issues(self, count=5, state="open"):
            return {
                "ok": True,
                "items": [_make_issue(number=12, title="Fix login error")],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    for message in [
        "Issueを見せて",
        "Issue一覧を教えて",
        "未解決のIssueを教えて",
        "オープンなIssueを教えて",
    ]:
        text = handle_issue_or_pr_request(message)
        assert text is not None
        assert "【GitHub Issues】" in text
        assert "#12 Fix login error" in text


def test_handle_issue_or_pr_request_fetches_pull_requests_for_pr_queries(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_pull_requests(self, count=5, state="open"):
            return {
                "ok": True,
                "items": [_make_pr(number=25, title="Add GitHub Issue support")],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    for message in [
        "PRを見せて",
        "Pull Requestを教えて",
        "PR一覧を教えて",
        "オープン中のPRを教えて",
    ]:
        text = handle_issue_or_pr_request(message)
        assert text is not None
        assert "【GitHub Pull Requests】" in text
        assert "#25 Add GitHub Issue support" in text


def test_handle_github_message_fetches_issues_for_natural_language_request(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_issues(self, count=5, state="open"):
            return {
                "ok": True,
                "items": [_make_issue(number=12, title="Fix login error")],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    text = handle_github_message("nonkun12/line-botのIssueを教えて", user_id="user123")

    assert "【GitHub Issues】" in text
    assert "#12 Fix login error" in text


def test_handle_github_message_fetches_pull_requests_for_natural_language_request(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_pull_requests(self, count=5, state="open"):
            return {
                "ok": True,
                "items": [_make_pr(number=25, title="Add GitHub Issue support")],
                "error": None,
                "status": 200,
            }

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    text = handle_github_message("nonkun12/line-botのPRを教えて", user_id="user123")

    assert "【GitHub Pull Requests】" in text
    assert "#25 Add GitHub Issue support" in text


def test_handle_latest_repo_info_calls_client_and_formats_result(monkeypatch):
    from agents.github import handlers

    messages = [
        "最新のGitHubリポジトリを教えて",
        "GitHubのリポジトリを教えて",
        "GitHubリポジトリ情報を教えて",
        "GitHub repo info",
    ]

    fake_repo = {
        "full_name": "nonkun12/line-bot",
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 1,
        "html_url": "https://github.com/nonkun12/line-bot",
    }

    class FakeClient:
        def get_repo_info(self):
            return fake_repo

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    for message in messages:
        result = handlers.handle_latest_repo_info(message)
        assert result == handlers.format_repo_info(fake_repo)


def test_handle_latest_repo_info_returns_none_for_non_repo_info_queries():
    from agents.github import handlers

    assert handlers.handle_latest_repo_info("最新コミットを教えて") is None
    assert handlers.handle_latest_repo_info("GitHubでPythonを検索して") is None
    assert handlers.handle_latest_repo_info("Issueを確認して") is None
    assert handlers.handle_latest_repo_info("今日は天気がいいですね") is None


def test_handle_github_message_natural_language_repo_info(monkeypatch):
    from agents.github import handlers

    fake_repo = {
        "full_name": "nonkun12/line-bot",
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 1,
        "html_url": "https://github.com/nonkun12/line-bot",
    }

    class FakeClient:
        def get_repo_info(self):
            return fake_repo

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    result = handlers.handle_github_message(
        "最新のGitHubリポジトリを教えて",
        "user123",
    )

    assert result == handlers.format_repo_info(fake_repo)


def test_handle_github_message_github_repo_exact_command_still_works(monkeypatch):
    from agents.github import handlers

    fake_repo = {
        "full_name": "nonkun12/line-bot",
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 1,
        "html_url": "https://github.com/nonkun12/line-bot",
    }

    class FakeClient:
        def get_repo_info(self):
            return fake_repo

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    result = handlers.handle_github_message(
        "github repo",
        "user123",
    )

    assert result == handlers.format_repo_info(fake_repo)


def test_handle_github_message_commits_search_file_not_shadowed_by_repo_info(monkeypatch):
    from agents.github import handlers

    class FakeClient:
        def get_latest_commits(self):
            return []

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    result = handlers.handle_github_message(
        "github commits",
        "user123",
    )

    assert result == "コミットが見つかりませんでした。"


# ---------------------------------------------------------------------------
# Natural-language file content requests (handle_file_contents)
# ---------------------------------------------------------------------------

def test_handle_file_contents_extracts_path_and_calls_client(monkeypatch):
    calls = []

    class FakeClient:
        def get_file_contents(self, path):
            calls.append(path)
            return f"# contents of {path}"

    monkeypatch.setattr(
        "agents.github.handlers.GitHubClient", FakeClient
    )

    cases = [
        ("app.pyのファイル内容を見せて", "app.py"),
        ("app.pyを表示して", "app.py"),
        ("README.mdの内容を見せて", "README.md"),
        ("GitHubのapp.pyを見せて", "app.py"),
    ]

    for message, expected_path in cases:
        result = handle_file_contents(message)
        assert result == f"# contents of {expected_path}"

    assert calls == ["app.py", "app.py", "README.md", "app.py"]


def test_handle_file_contents_returns_none_for_unrelated_messages():
    assert handle_file_contents("今日は天気がいいですね") is None
    assert handle_file_contents("最新コミットを教えて") is None
    assert handle_file_contents("githubで requests 探して") is None
    # 既存の完全一致コマンドは別ルートで処理されるため、自然文ハンドラ
    # 単体としては拾わない(handle_github_message側の順序で非衝突)。
    assert handle_file_contents("github file app.py") is None


def test_handle_file_contents_passes_through_client_error_message(monkeypatch):
    class FakeClient:
        def get_file_contents(self, path):
            return "GitHub API error: 404"

    monkeypatch.setattr(
        "agents.github.handlers.GitHubClient", FakeClient
    )

    result = handle_file_contents("missing.pyの内容を見せて")

    assert result == "GitHub API error: 404"


def test_handle_file_contents_passes_through_client_exception_message(monkeypatch):
    class FakeClient:
        def get_file_contents(self, path):
            return "network down"

    monkeypatch.setattr(
        "agents.github.handlers.GitHubClient", FakeClient
    )

    result = handle_file_contents("app.pyを表示して")

    assert result == "network down"


def test_handle_github_message_natural_language_file_contents(monkeypatch):
    from agents.github import handlers

    class FakeClient:
        def get_file_contents(self, path):
            assert path == "app.py"
            return "print('hello')"

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    result = handlers.handle_github_message(
        "app.pyのファイル内容を見せて",
        "user123",
    )

    assert result == "print('hello')"


def test_handle_github_message_github_file_exact_command_still_works(monkeypatch):
    """
    Regression: the pre-existing "github file <path>" exact command must
    keep working unchanged after adding natural-language file content
    support. This command is matched before the natural-language handler
    chain runs, so it must not be shadowed by handle_file_contents().
    """
    from agents.github import handlers

    calls = []

    class FakeClient:
        def get_file_contents(self, path):
            calls.append(path)
            return "print('from exact command')"

    monkeypatch.setattr(handlers, "GitHubClient", FakeClient)

    result = handlers.handle_github_message(
        "github file app.py",
        "user123",
    )

    assert result == "print('from exact command')"
    assert calls == ["app.py"]


def test_handle_github_message_github_file_missing_filename_still_works(monkeypatch):
    """Regression: unchanged behavior when no filename is given."""
    from agents.github import handlers

    result = handlers.handle_github_message(
        "github file",
        "user123",
    )

    assert result == "ファイル名を指定してください。"


# ---------------------------------------------------------------------------
# GitHubClient.get_file_contents() contract (previously untested)
# ---------------------------------------------------------------------------

def test_client_get_file_contents_decodes_base64_content(monkeypatch):
    import base64

    encoded = base64.b64encode(b"print('hi')").decode("ascii")

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(
            200,
            {"content": encoded, "encoding": "base64"},
        )

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.get_file_contents("app.py")

    assert result == "print('hi')"


def test_client_get_file_contents_returns_error_message_on_non_200(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.get_file_contents("missing.py")

    assert result == "GitHub API error: 404"


def test_client_get_file_contents_returns_error_message_on_exception(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr("agents.github.client.requests.get", fake_get)

    client = GitHubClient(token="dummy")
    result = client.get_file_contents("app.py")

    assert "network down" in result


def test_client_get_file_contents_returns_error_when_repo_not_configured():
    # GitHubClient.__init__ always falls back to a default repo name, so
    # the "not configured" branch is reached by clearing the attribute
    # directly after construction rather than via the constructor.
    client = GitHubClient(token="dummy")
    client.repo = None

    result = client.get_file_contents("app.py")

    assert result == "GITHUB_REPO is not configured"
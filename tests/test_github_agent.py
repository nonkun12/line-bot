from agents.github.node import github_agent_node
from agents.github.intents import is_github_intent, is_issue_or_pr_intent
from agents.github.handlers import (
    handle_latest_commits,
    handle_github_search,
    handle_issue_or_pr_request,
    handle_github_message,
    format_search_results,
    format_commits,
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
# Issue / Pull Request intent recognition (Phase3-5 - intent only, no API)
# ---------------------------------------------------------------------------

def test_is_issue_or_pr_intent_detects_issue_and_pr_queries():
    assert is_issue_or_pr_intent("PRある？")
    assert is_issue_or_pr_intent("Issueを確認して")
    assert is_issue_or_pr_intent("プルリクエストを見せて")
    assert is_issue_or_pr_intent("pull request please")


def test_is_issue_or_pr_intent_returns_false_for_unrelated_messages():
    assert not is_issue_or_pr_intent("今日は天気がいいですね")
    assert not is_issue_or_pr_intent("最新コミットを教えて")


def test_handle_issue_or_pr_request_returns_not_supported_message():
    for message in ["PRある？", "Issueを確認して", "プルリクエストを見せて"]:
        text = handle_issue_or_pr_request(message)
        assert text is not None
        assert "未対応" in text


def test_handle_issue_or_pr_request_returns_none_for_unrelated_messages():
    assert handle_issue_or_pr_request("今日は天気がいいですね") is None


def test_handle_github_message_returns_not_supported_for_issue_or_pr(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("agents.github.handlers.GitHubClient", FakeClient)

    text = handle_github_message("PRある？", user_id="user123")

    assert "未対応" in text

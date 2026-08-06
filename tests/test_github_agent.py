from agents.github.node import github_agent_node
from agents.github.intents import is_github_intent
from agents.github.handlers import handle_latest_commits


def test_github_agent_node_returns_placeholder_text():
    result = github_agent_node(
        {
            "user_id": "user123",
            "raw_message": "GitHubの最新コミットを教えて",
            "agent_results": {},
        }
    )

    assert result["agent_results"]["github"]["text"] == "最新コミット取得機能はまだ準備中です。"


def test_handle_latest_commits_returns_placeholder_for_latest_commit_queries():
    assert handle_latest_commits("最新コミットを教えて") == "最新コミット取得機能はまだ準備中です。"
    assert handle_latest_commits("latest commit please") == "最新コミット取得機能はまだ準備中です。"
    assert handle_latest_commits("commit historyを見せて") == "最新コミット取得機能はまだ準備中です。"


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

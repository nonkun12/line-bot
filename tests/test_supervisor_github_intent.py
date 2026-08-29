"""
Phase3-5: Supervisor's GitHub intent classification.

Verifies that classify_intent() now uses agents.github.intents.is_github_intent()
instead of a naive `text.startswith("github")` check, so natural-language
GitHub requests are routed to the GitHub Agent via the existing
Supervisor -> Router -> github_agent -> Finalizer structure.
"""

from graph.supervisor import classify_intent, supervisor_node


def test_classify_intent_routes_natural_language_github_requests_to_github():
    messages = [
        "最新コミットを教えて",
        "このリポジトリのコミットを見せて",
        "GitHubのコミットを確認して",
        "PRある？",
        "Issueを確認して",
    ]

    for message in messages:
        assert classify_intent(message) == "github"


def test_classify_intent_still_routes_explicit_github_prefix():
    assert classify_intent("github repo") == "github"
    assert classify_intent("github search line bot") == "github"


def test_classify_intent_routes_natural_language_file_content_requests_to_github():
    """
    Regression test: natural-language file content requests like
    "README.mdを見せて" were previously misrouted to the Normal Agent
    because classify_intent()/is_github_intent() had no way to recognize
    them, even though the GitHub Agent's handle_file_contents() already
    supported this phrasing via "github file <path>".
    """
    messages = [
        "README.mdを見せて",
        "README.mdの内容を見せて",
        "README.mdを表示して",
        "app.pyを表示して",
        "github file README.md",
    ]

    for message in messages:
        assert classify_intent(message) == "github"


def test_classify_intent_does_not_route_unrelated_readme_questions_to_github():
    assert classify_intent("READMEの書き方を教えて") == "unsupported"
    assert classify_intent("READMEって何ですか？") == "unsupported"


def test_classify_intent_still_routes_debug_prefix():
    assert classify_intent("debug something broke") == "debug"


def test_classify_intent_returns_unsupported_for_unrelated_messages():
    # Weather intent is intentionally recognized by the current Supervisor.
    assert classify_intent("今日は天気がいいですね") == "weather"


def test_supervisor_node_sets_next_agent_to_github_for_natural_language_request():
    state = {
        "user_id": "user123",
        "raw_message": "最新コミットを教えて",
    }

    result = supervisor_node(state)

    assert result["intent"] == "github"
    assert result["next_agent"] == "github"

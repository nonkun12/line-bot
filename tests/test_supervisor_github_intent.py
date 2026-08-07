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


def test_classify_intent_still_routes_debug_prefix():
    assert classify_intent("debug something broke") == "debug"


def test_classify_intent_returns_unsupported_for_unrelated_messages():
    assert classify_intent("今日は天気がいいですね") == "unsupported"


def test_supervisor_node_sets_next_agent_to_github_for_natural_language_request():
    state = {
        "user_id": "user123",
        "raw_message": "最新コミットを教えて",
    }

    result = supervisor_node(state)

    assert result["intent"] == "github"
    assert result["next_agent"] == "github"

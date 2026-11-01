from agents.github.intents import (
    is_github_intent,
    is_issue_or_pr_intent,
    is_pull_request_intent,
    is_issue_intent,
)


def test_negated_repository_and_deployment_operations_do_not_route_to_github():
    message = (
        "「サーバー側ルーティングOK」とだけ返答してください。"
        "リポジトリ変更、コード実行、デプロイなどの操作はしないでください。"
    )
    assert is_github_intent(message) is False


def test_positive_github_request_still_routes_to_github():
    assert is_github_intent("リポジトリの最新コミットを確認してください") is True


def test_positive_github_request_survives_separate_negated_safety_clause():
    message = (
        "リポジトリの最新状態を確認してください。"
        "リポジトリ変更、コード実行、デプロイなどの操作はしないでください。"
    )
    assert is_github_intent(message) is True



def test_line_receipt_status_request_does_not_route_to_github_pr_listing():
    message = (
        "line-botの開発指示受付が正常に動作するかテストしてください。"
        "コード変更・PR作成・マージ・デプロイは行わず、"
        "受付結果とGitHub Actionsへの連携状況だけ報告してください。"
    )
    assert is_github_intent(message) is False


def test_negated_pr_creation_and_merge_operations_do_not_route_to_github():
    message = "コード変更・PR作成・マージ・デプロイは行わず、受付結果だけ報告してください。"
    assert is_github_intent(message) is False



def test_receipt_only_line_connectivity_message_does_not_route_to_any_github_handler():
    from agents.github.intents import (
        is_github_intent,
        is_issue_or_pr_intent,
        is_pull_request_intent,
        is_issue_intent,
    )

    message = (
        "疎通テストです。LINEからのメッセージ受信と返信が正常に動作するか確認してください。"
        "GitHubの検索・Actions起動・コード変更・PR作成・マージ・デプロイは一切行わないでください。"
        "「LINE受信成功」「返信成功」「GitHub連携の有無」だけ報告してください。"
    )
    assert is_github_intent(message) is False
    assert is_issue_or_pr_intent(message) is False
    assert is_pull_request_intent(message) is False
    assert is_issue_intent(message) is False


def test_status_only_request_does_not_route_to_pr_listing_even_when_pr_creation_is_negated():
    from agents.github.intents import is_pull_request_intent

    message = (
        "PR作成・マージ・デプロイは行わず、"
        "受付結果とGitHub Actionsへの連携状況だけ報告してください。"
    )
    assert is_pull_request_intent(message) is False



def test_exact_line_connectivity_smoke_message_does_not_route_to_github_or_prs():
    message = (
        "疎通テストです。LINEからのメッセージ受信と返信が正常に動作するか確認してください。"
        "GitHubの検索・Actions起動・コード変更・PR作成・マージ・デプロイは一切行わないでください。"
        "「LINE受信成功」「返信成功」「GitHub連携の有無」だけ報告してください。"
    )
    assert is_github_intent(message) is False
    assert is_issue_or_pr_intent(message) is False
    assert is_pull_request_intent(message) is False
    assert is_issue_intent(message) is False


def test_explicitly_negated_pr_creation_is_not_a_pr_query():
    message = "GitHubの検索・PR作成・マージは一切行わないでください。"
    assert is_issue_or_pr_intent(message) is False
    assert is_pull_request_intent(message) is False

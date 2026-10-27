from agents.github.intents import is_github_intent


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

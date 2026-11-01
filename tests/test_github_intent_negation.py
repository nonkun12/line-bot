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

from core.task_routing import TaskClassifier, TaskMode


def test_line_e2e_development_requests_are_secretary_self_improvement():
    result = TaskClassifier().classify("開発: 本線E2Eテストを実行してください")
    assert result.mode == TaskMode.SELF_IMPROVEMENT
    assert result.project_repository == "nonkun12/line-bot"


def test_line_e2e_implementation_requests_are_secretary_self_improvement():
    result = TaskClassifier().classify("開発: E2Eテストを実装してください")
    assert result.mode == TaskMode.SELF_IMPROVEMENT
    assert result.project_repository == "nonkun12/line-bot"

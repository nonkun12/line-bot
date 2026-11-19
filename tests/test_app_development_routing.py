from app_development import extract_app_development_request


def test_explicit_app_development_prefix_still_routes():
    assert extract_app_development_request("アプリ開発: TODOアプリを作って") == "TODOアプリを作って"


def test_natural_todo_app_creation_routes():
    assert extract_app_development_request("TODOアプリを作って") == "TODOアプリを作って"


def test_natural_app_creation_with_requirements_routes():
    message = "シンプルなWebアプリを作成して。タスクの追加・完了・削除ができるようにして"
    assert extract_app_development_request(message) == message


def test_app_building_question_does_not_dispatch():
    assert extract_app_development_request("TODOアプリの作り方を教えて") is None


def test_natural_app_requirement_is_bounded():
    message = "TODOアプリを作って " + ("x" * 4000)
    result = extract_app_development_request(message)
    assert result is not None
    assert len(result) == 3000

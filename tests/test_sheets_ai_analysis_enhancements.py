from unittest.mock import MagicMock, patch

from agents.sheets.handlers import handle_sheets_message


def _mock_ai_response(text):
    response = MagicMock()
    response.choices[0].message.content = text
    return response


def test_priority_request_uses_ai_analysis():
    client = MagicMock()
    client.read_rows.return_value = [["Amazon打合せ"], ["請求書"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("Amazon打合せを優先してください。")
        result = handle_sheets_message("シートから優先順位をつけて", "user123", client)

    assert result["success"] is True
    assert result["text"] == "Amazon打合せを優先してください。"
    client.read_rows.assert_called_once_with("A:Z")
    mock_generate.assert_called_once()


def test_tasks_to_do_request_uses_ai_analysis():
    client = MagicMock()
    client.read_rows.return_value = [["明日の予定"], ["資料作成"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("まず資料作成です。")
        result = handle_sheets_message("今やるべきことを整理して", "user123", client)

    assert result["success"] is True
    assert result["text"] == "まず資料作成です。"
    mock_generate.assert_called_once()


def test_task_request_uses_ai_analysis():
    client = MagicMock()
    client.read_rows.return_value = [["タスクA"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("タスクAです。")
        result = handle_sheets_message("タスクを整理して", "user123", client)

    assert result["success"] is True
    mock_generate.assert_called_once()


def test_advice_request_uses_ai_analysis():
    client = MagicMock()
    client.read_rows.return_value = [["予定A"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("予定Aを優先するとよいです。")
        result = handle_sheets_message("シートを見てアドバイスして", "user123", client)

    assert result["success"] is True
    mock_generate.assert_called_once()


def test_unknown_natural_sheets_question_falls_back_to_ai_analysis():
    client = MagicMock()
    client.read_rows.return_value = [["Amazon打合せ"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("Amazon打合せについて記録があります。")
        result = handle_sheets_message("このシートについて質問したい", "user123", client)

    assert result["success"] is True
    assert result["text"] == "Amazon打合せについて記録があります。"
    client.read_rows.assert_called_once_with("A:Z")
    mock_generate.assert_called_once()


def test_bare_sheet_mention_does_not_fall_back_to_ai():
    client = MagicMock()

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        result = handle_sheets_message("シート", "user123", client)

    assert result is None
    client.read_rows.assert_not_called()
    mock_generate.assert_not_called()


def test_ai_context_is_limited_to_200_rows():
    client = MagicMock()
    client.read_rows.return_value = [[f"row-{i}"] for i in range(1, 206)]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("分析結果")
        result = handle_sheets_message("シートの内容を分析して", "user123", client)

    assert result["success"] is True
    assert len(result["rows"]) == 205

    messages = mock_generate.call_args.kwargs["messages"]
    system_content = messages[0]["content"]
    assert "row-200" in system_content
    assert "row-201" not in system_content
    assert "全205行" in system_content
    assert "先頭200行" in system_content


def test_ai_context_has_no_truncation_note_for_200_rows():
    client = MagicMock()
    client.read_rows.return_value = [[f"row-{i}"] for i in range(1, 201)]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        mock_generate.return_value = _mock_ai_response("分析結果")
        handle_sheets_message("シートの内容を分析して", "user123", client)

    system_content = mock_generate.call_args.kwargs["messages"][0]["content"]
    assert "row-200" in system_content
    assert "行数が多いため" not in system_content

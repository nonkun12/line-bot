from unittest.mock import MagicMock, patch

from agents.sheets.handlers import handle_sheets_message


def test_handle_sheets_message_search():
    client = MagicMock()
    client.search.return_value = [["Amazon打合せ"]]

    result = handle_sheets_message(
        "シートから検索 Amazon",
        "user123",
        client,
    )

    assert result["success"] is True
    assert result["rows"] == [["Amazon打合せ"]]
    client.search.assert_called_once_with("A:Z", "Amazon")


def test_handle_sheets_message_read():
    client = MagicMock()
    client.read_rows.return_value = [["テスト"]]

    result = handle_sheets_message(
        "シートを見て",
        "user123",
        client,
    )

    assert result["success"] is True
    assert result["rows"] == [["テスト"]]
    client.read_rows.assert_called_once_with("A:Z")


def test_handle_sheets_message_append():
    client = MagicMock()

    result = handle_sheets_message(
        "シートに記録 テストデータ",
        "user123",
        client,
    )

    assert result["success"] is True
    client.append_row.assert_called_once_with(
        "A:A",
        ["テストデータ"],
    )


def test_handle_sheets_message_delete():
    client = MagicMock()
    client.search.return_value = [
        ["Amazon打合せ"],
    ]

    result = handle_sheets_message(
        "シートから Amazon打合せ を削除して",
        "user123",
        client,
    )

    assert result["success"] is True
    client.search.assert_called_once_with(
        "A:Z",
        "Amazon打合せ",
    )
    client.delete_row.assert_called_once_with(
        "Amazon打合せ",
    )
    client.delete_row.assert_called_once()


def _mock_ai_response(text):
    """generate_chat_completionのレスポンス形状を模したMagicMockを作る。"""
    response = MagicMock()
    response.choices[0].message.content = text
    return response


@patch("agents.sheets.handlers.generate_chat_completion")
def test_handle_sheets_message_ai_analysis_uses_sheet_context(mock_generate):
    """
    「シートの内容を分析して」のような自然文の質問では、
    Google Sheetsから取得した現在のデータをAIへコンテキストとして渡し、
    AIが生成した自然文の回答をそのまま返すこと。
    外部AI APIには依存せず、generate_chat_completionをモックして検証する。
    """
    client = MagicMock()
    client.read_rows.return_value = [
        ["テスト1"],
        ["Amazon打合せ"],
        ["明日の予定"],
    ]
    mock_generate.return_value = _mock_ai_response(
        "重要な予定はAmazon打合せです。"
    )

    result = handle_sheets_message(
        "シートの内容を見て、重要な予定を教えて",
        "user123",
        client,
    )

    assert result["success"] is True
    assert result["text"] == "重要な予定はAmazon打合せです。"
    assert result["rows"] == [
        ["テスト1"],
        ["Amazon打合せ"],
        ["明日の予定"],
    ]

    client.read_rows.assert_called_once_with("A:Z")
    mock_generate.assert_called_once()

    call_kwargs = mock_generate.call_args.kwargs
    messages = call_kwargs["messages"]

    assert messages[0]["role"] == "system"
    assert "Amazon打合せ" in messages[0]["content"]
    assert messages[1] == {
        "role": "user",
        "content": "シートの内容を見て、重要な予定を教えて",
    }


@patch("agents.sheets.handlers.generate_chat_completion")
def test_handle_sheets_message_ai_analysis_about_specific_topic(mock_generate):
    client = MagicMock()
    client.read_rows.return_value = [["Amazon打合せ", "14時から"]]
    mock_generate.return_value = _mock_ai_response(
        "Amazon打合せは14時からと書かれています。"
    )

    result = handle_sheets_message(
        "Amazon打合せについてシートに何が書いてある？",
        "user123",
        client,
    )

    assert result["success"] is True
    assert result["text"] == "Amazon打合せは14時からと書かれています。"
    client.read_rows.assert_called_once_with("A:Z")


@patch("agents.sheets.handlers.generate_chat_completion")
def test_handle_sheets_message_ai_analysis_empty_sheet(mock_generate):
    """シートが空でもエラーにならず、AIにその旨を伝えて呼び出すこと。"""
    client = MagicMock()
    client.read_rows.return_value = []
    mock_generate.return_value = _mock_ai_response(
        "シートにはまだ何も記録されていないようです。"
    )

    result = handle_sheets_message(
        "シートの内容を簡単にまとめて",
        "user123",
        client,
    )

    assert result["success"] is True
    assert "記録されていない" in result["text"]

    call_kwargs = mock_generate.call_args.kwargs
    system_content = call_kwargs["messages"][0]["content"]
    assert "シートにはまだデータがありません" in system_content


@patch("agents.sheets.handlers.generate_chat_completion")
def test_handle_sheets_message_ai_analysis_falls_back_on_api_error(mock_generate):
    """AI呼び出しが失敗しても例外を送出せず、エラー用の返信を返すこと。"""
    client = MagicMock()
    client.read_rows.return_value = [["テスト1"]]
    mock_generate.side_effect = Exception("groq api error")

    result = handle_sheets_message(
        "シートの内容を分析して",
        "user123",
        client,
    )

    assert result["success"] is True
    assert "エラー" in result["text"]


def test_handle_sheets_message_plain_read_does_not_call_ai():
    """
    分析トリガーワードを含まない単純な「シートを見て」は、
    従来通りAIを呼ばず生データの一覧表示のままであること。
    """
    client = MagicMock()
    client.read_rows.return_value = [["テスト"]]

    with patch("agents.sheets.handlers.generate_chat_completion") as mock_generate:
        result = handle_sheets_message(
            "シートを見て",
            "user123",
            client,
        )
        mock_generate.assert_not_called()

    assert result["success"] is True
    assert result["text"].startswith("Google Sheetsの内容：")

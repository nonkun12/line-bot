from unittest.mock import MagicMock

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

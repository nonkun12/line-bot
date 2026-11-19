from mcp_client import parse_mcp_json_list


def test_parse_mcp_json_list_accepts_legacy_reminder_text_without_json_error(capsys):
    raw = 'id=452: 2026/9/10 10:00:00 に「明日の10時にテストするとメモして」'

    result = parse_mcp_json_list(raw)

    assert result == [
        {
            "id": 452,
            "remind_at": "2026/9/10 10:00:00",
            "message": "明日の10時にテストするとメモして",
            "repeat": "none",
        }
    ]
    assert "parse error:" not in capsys.readouterr().out


def test_parse_mcp_json_list_still_parses_json_lists():
    raw = '[{"id": 1, "message": "test"}]'
    assert parse_mcp_json_list(raw) == [{"id": 1, "message": "test"}]

import os
import sys
from unittest.mock import patch

# app.py はimport時にos.environ[...]を直接参照するため、
# importより前に必要な環境変数をダミー値で用意しておく。
os.environ.setdefault("CHANNEL_ACCESS_TOKEN", "dummy")
os.environ.setdefault("CHANNEL_SECRET", "dummy")
os.environ.setdefault("GROQ_API_KEY", "dummy")
os.environ.setdefault("MCP_SERVER_URL", "https://example.com/mcp")
os.environ.setdefault("MCP_API_KEY", "dummy")
os.environ.setdefault("INTERNAL_PUSH_KEY", "dummy")

sys.path.insert(0, os.path.dirname(__file__))
import app  # noqa: E402


def _dispatch_save_memory(key, value, original_message):
    """
    dispatch_tool_call経由でsave_memoryを実行し、
    call_mcp_toolへ渡されたargumentsを検証する。
    call_mcp_tool自体は実際のMCPサーバーへHTTPリクエストするため、モックする。
    """
    with patch.object(app, "call_mcp_tool") as mock_call:
        mock_call.return_value = "OK"
        app.dispatch_tool_call(
            "test_user",
            "save_memory",
            {"key": key, "value": value},
            original_message=original_message,
        )
        assert mock_call.called
        called_name, called_args = mock_call.call_args[0]
        assert called_name == "save_memory"
        return called_args


def test_favorite_food_is_cleaned():
    args = _dispatch_save_memory(
        "favorite_food",
        "好きな食べ物は寿司です",
        "好きな食べ物は寿司です",
    )
    assert args["key"] == "favorite_food"
    assert args["value"] == "寿司"


def test_favorite_drink_is_cleaned():
    args = _dispatch_save_memory(
        "favorite_drink",
        "好きな飲み物はコーヒーです",
        "好きな飲み物はコーヒーです",
    )
    assert args["key"] == "favorite_drink"
    assert args["value"] == "コーヒー"


def test_name_is_cleaned():
    args = _dispatch_save_memory(
        "name",
        "私の名前はnonkunです",
        "私の名前はnonkunです",
    )
    assert args["key"] == "name"
    assert args["value"] == "nonkun"


def test_study_plan_is_kept_as_is():
    original_value = "Pythonの基礎を1週間で学習する"
    args = _dispatch_save_memory(
        "study_plan",
        original_value,
        "Pythonの基礎を1週間で学習する予定です",
    )
    assert args["key"] == "study_plan"
    # study_planは既存処理どおり、valueをそのまま維持する
    assert args["value"] == original_value


def test_memory_key_classification_still_works():
    # 既存処理: key="memory" の場合、原文の内容から適切なkeyへ分類する。
    # 分類後、favorite_foodなのでvalueも整理されることを確認する。
    args = _dispatch_save_memory(
        "memory",
        "好きな食べ物は寿司です",
        "好きな食べ物は寿司です",
    )
    assert args["key"] == "favorite_food"
    assert args["value"] == "寿司"


def test_quoted_text_still_takes_priority():
    # 既存処理: 「」/『』で明示された文言があれば、そちらをそのまま優先して使う。
    # 「寿司」自体は好きな食べ物の定型文パターンにマッチしないため、そのまま維持される。
    args = _dispatch_save_memory(
        "favorite_food",
        "好きな食べ物は寿司です",
        "好きな食べ物は「寿司」です、覚えておいて",
    )
    assert args["key"] == "favorite_food"
    assert args["value"] == "寿司"


def test_name_intent_pattern_still_forces_name_key():
    # 既存処理: NAME_INTENT_PATTERNに一致する原文なら、keyをnameへ強制的に統一する。
    args = _dispatch_save_memory(
        "username",
        "私の名前はnonkunです",
        "私の名前はnonkunです",
    )
    assert args["key"] == "name"
    assert args["value"] == "nonkun"


def test_question_message_still_skips_save():
    with patch.object(app, "call_mcp_tool") as mock_call:
        result = app.dispatch_tool_call(
            "test_user",
            "save_memory",
            {"key": "favorite_food", "value": "好きな食べ物は？"},
            original_message="好きな食べ物は？",
        )
        mock_call.assert_not_called()
        assert "スキップ" in result


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
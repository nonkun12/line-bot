import os
import sys
from unittest.mock import patch, MagicMock

# モック環境変数の設定
os.environ["CHANNEL_ACCESS_TOKEN"] = "dummy_token"
os.environ["CHANNEL_SECRET"] = "dummy_secret"
os.environ["GROQ_API_KEY"] = "dummy_groq_key"
os.environ["MCP_SERVER_URL"] = "http://dummy-mcp-server/mcp"
os.environ["MCP_API_KEY"] = "dummy_mcp_key"
os.environ["INTERNAL_PUSH_KEY"] = "dummy_push_key"

# app.pyがロードされるパスを追加
sys.path.append("/Users/manabenorimitsu1/Desktop/line-bot")

import app

# テスト項目
# 1. 覚えて ○○ -> save_memory 成功（AIを介さないルート）
# 2. ○○は？（ここでは"私の名前は？" "名前は？" "私の名前を教えて"など） -> 記憶から回答（AIを介さないルート）
# 3. メモして ○○ -> save_note 成功（AIを介さないルート）
# 4. メモ検索 ○○ -> search_notes 成功（AIを介さないルート）
# 5. 通常の会話（例: 「好きな果物は？」）の時にGroq APIに渡される tools と system_prompt の内容を検証
# 6. 「〜は？」で終わる質問文の場合は save_memory がスキップされること
# 7. 「〜は〇〇」という普通の文の場合は save_memory が通常通り実行されること
# 8. 「覚えて」「覚えておいて」「記憶して」「記憶してください」が保存値から除去されること
# 9. key="memory" の場合、内容（好きな食べ物、好きな飲み物、私の名前/名前は、Python）に応じて自動分類されること

def test_save_memory():
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "記憶しました"
        res = app.generate_reply("user123", "覚えて 私の名前はたろう")
        
        # 呼ばれるべきツールを確認
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "name",
            "value": "たろう"
        })
        assert res == "記憶しました"
        print("PASS: 覚えて ○○ -> save_memory")

def test_get_memory_direct():
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "たろう"
        res = app.generate_reply("user123", "私の名前は？")
        
        mock_call.assert_called_with("get_memory", {
            "user_id": "user123",
            "key": "name"
        })
        assert res == "たろう"
        print("PASS: ○○は？ -> get_memory")

def test_save_note():
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "メモを保存しました"
        res = app.generate_reply("user123", "メモして 今日はテニスの日")
        
        mock_call.assert_called_with("save_note", {
            "user_id": "user123",
            "title": "LINEメモ",
            "body": "今日はテニスの日",
            "category": "一般"
        })
        assert res == "メモを保存しました"
        print("PASS: メモして ○○ -> save_note")

def test_search_notes():
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "検索結果はありません"
        res = app.generate_reply("user123", "メモ検索 テニス")
        
        mock_call.assert_called_with("search_notes", {
            "user_id": "user123",
            "keyword": "テニス"
        })
        assert res == "検索結果はありません"
        print("PASS: メモ検索 ○○ -> search_notes")

def test_save_memory_query():
    # 質問形式「好きな飲み物は？」 -> save_memory がスキップされることを確認
    # dispatch_tool_call を直接呼び出してテスト
    res = app.dispatch_tool_call("user123", "save_memory", {"key": "favorite_drink", "value": "コーヒー"}, original_message="好きな飲み物は？")
    assert "スキップされました" in res
    print("PASS: 質問形式（好きな飲み物は？） -> save_memoryスキップ")

    res_en = app.dispatch_tool_call("user123", "save_memory", {"key": "favorite_drink", "value": "コーヒー"}, original_message="好きな飲み物は?")
    assert "スキップされました" in res_en
    print("PASS: 質問形式（好きな飲み物は?） -> save_memoryスキップ")

def test_save_memory_statement():
    # 記述形式「好きな飲み物はコーヒー」 -> save_memory がスキップされずに通常通り呼ばれることを確認
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "記憶しました"
        res = app.dispatch_tool_call("user123", "save_memory", {"key": "favorite_drink", "value": "コーヒー"}, original_message="好きな飲み物はコーヒー")
        
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "favorite_drink",
            "value": "コーヒー"
        })
        assert res == "記憶しました"
        print("PASS: 記述形式（好きな飲み物はコーヒー） -> save_memory通常実行")

def test_save_memory_clean_words():
    # 「覚えて」「覚えておいて」「記憶して」「記憶してください」が含まれている場合に除去されることを確認
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "記憶しました"
        
        # 覚えておいて の除去
        app.dispatch_tool_call("user123", "save_memory", {"key": "hobby", "value": "私の趣味はテニスだと覚えておいて"}, original_message="私の趣味はテニスだと覚えておいて")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "hobby",
            "value": "私の趣味はテニスだと"
        })
        
        # 覚えて の除去
        app.dispatch_tool_call("user123", "save_memory", {"key": "hobby", "value": "私の趣味はテニスだと覚えて"}, original_message="私の趣味はテニスだと覚えて")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "hobby",
            "value": "私の趣味はテニスだと"
        })

        # 記憶して の除去
        app.dispatch_tool_call("user123", "save_memory", {"key": "hobby", "value": "私の趣味はテニスだと記憶して"}, original_message="私の趣味はテニスだと記憶して")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "hobby",
            "value": "私の趣味はテニスだと"
        })

        # 記憶してください の除去
        app.dispatch_tool_call("user123", "save_memory", {"key": "hobby", "value": "私の趣味はテニスだと記憶してください"}, original_message="私の趣味はテニスだと記憶してください")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "hobby",
            "value": "私の趣味はテニスだと"
        })
        
        print("PASS: 命令文の除去（覚えて、覚えておいて、記憶して、記憶してください）")

def test_save_memory_auto_classify():
    with patch("app.call_mcp_tool") as mock_call:
        mock_call.return_value = "記憶しました"

        # 1. 好きな食べ物 -> favorite_food
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "私の好きな食べ物はラーメンです"}, original_message="私の好きな食べ物はラーメンです")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "favorite_food",
            "value": "ラーメン"
        })

        # 2. 好きな飲み物 -> favorite_drink
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "好きな飲み物はコーラ"}, original_message="好きな飲み物はコーラ")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "favorite_drink",
            "value": "コーラ"
        })

        # 3. 私の名前 -> name
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "太郎"}, original_message="私の名前は太郎です")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "name",
            "value": "太郎"
        })

        # 4. 名前は -> name
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "太郎"}, original_message="名前は太郎")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "name",
            "value": "太郎"
        })

        # 5. Python -> study_plan
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "Pythonの勉強をする"}, original_message="Pythonの勉強をする")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "study_plan",
            "value": "Pythonの勉強をする"
        })

        # 6. その他 -> memory
        app.dispatch_tool_call("user123", "save_memory", {"key": "memory", "value": "今日の天気は晴れ"}, original_message="今日の天気は晴れ")
        mock_call.assert_called_with("save_memory", {
            "user_id": "user123",
            "key": "memory",
            "value": "今日の天気は晴れ"
        })

        print("PASS: key='memory' の自動分類")

def test_groq_api_call_schema():
    # Groqの completions.create をモック化し、引数を確認する
    with patch("app.client.chat.completions.create") as mock_create, \
         patch("app.call_mcp_tool") as mock_call_mcp:
        
        mock_call_mcp.return_value = "[]" # get_all_memoryの結果（空）
        
        # 1回目のAI呼び出し用のモックレスポンス
        mock_choice = MagicMock()
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "私はりんごが好きです。"
        mock_res = MagicMock()
        mock_res.choices = [mock_choice]
        mock_create.return_value = mock_res
        
        reply = app.generate_reply("user123", "好きな果物は？")
        
        assert reply == "私はりんごが好きです。"
        
        # completions.create が呼び出された時の引数を確認
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        
        # 渡された tools の中に get_memory が存在しないことを確認
        tools = kwargs.get("tools", [])
        tool_names = [t["function"]["name"] for t in tools]
        assert "get_memory" not in tool_names, "get_memory が tools 一覧に含まれています！"
        
        # システムプロンプトの内容確認
        messages = kwargs.get("messages", [])
        system_msg = next((m for m in messages if m["role"] == "system"), None)
        assert system_msg is not None, "システムメッセージがありません"
        
        prompt_content = system_msg["content"]
        assert "記憶情報は既に提供されています。" in prompt_content
        assert "get_memoryツールは使用しないでください。" in prompt_content
        assert "ユーザーの発言が質問形式（「〜は？」で終わるもの）の場合、save_memory ツールは使用しないでください。" in prompt_content
        
        print("PASS: Groq API call Schema (No get_memory, Correct System Prompt, save_memory restriction)")

if __name__ == "__main__":
    test_save_memory()
    test_get_memory_direct()
    test_save_note()
    test_search_notes()
    test_save_memory_query()
    test_save_memory_statement()
    test_save_memory_clean_words()
    test_save_memory_auto_classify()
    test_groq_api_call_schema()
    print("ALL TESTS PASSED!")

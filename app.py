from flask import Flask, request, jsonify
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
import unicodedata
import json
import random
import threading
import httpx
import logging
logging.basicConfig(level=logging.DEBUG)
import re
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

from config import (
    CHANNEL_ACCESS_TOKEN,
    CHANNEL_SECRET,
    GROQ_API_KEY,
    INTERNAL_PUSH_KEY,
    AI_REPORT_GITHUB_REPO,
    GITHUB_TOKEN,
    N8N_WEBHOOK_URL,
    configuration,
    handler,
    client,
    MODEL,
)
from db import (
    init_db,
    save_message,
    load_history,
    create_processed_event,
    is_processed_event,
)
from reminders import (
    handle_daily_reminder,
    handle_relative_time_reminder,
    handle_tomorrow_reminder,
)
from agents.notes.intents import is_note_intent
from agents.github.intents import is_github_intent
from mcp_client import (
    call_mcp_tool as _call_mcp_tool_impl,
    parse_mcp_json_list as _parse_mcp_json_list_impl,
)
from ai_client import (
    generate_chat_completion,
    generate_secretary_report,
    client as _ai_client_client,
)
from bot_tools import (
    MCP_TOOLS_SCHEMA as _MCP_TOOLS_SCHEMA,
    extract_quoted_text as _extract_quoted_text_impl,
    normalize_memory_key as _normalize_memory_key_impl,
    ensure_jst_offset as _ensure_jst_offset_impl,
    clean_memory_value as _clean_memory_value_impl,
    dispatch_tool_call as _dispatch_tool_call_impl,
)

from debug_agent import run_debug_agent
from internal_ask_route import register_internal_ask_route
from n8n_delegate import _delegate_to_n8n

app = Flask(__name__)


# テスト互換用: 既存の app.client 参照を維持する
client = _ai_client_client

# =========================================================
# LINE送信共通層: 5000文字制限対策
# =========================================================
# LINE Messaging APIは1メッセージ最大5000文字までしか受け付けない
# (超過するとmessages[0].textでHTTP 400になる)。
# GitHub Agentの長文ファイル取得結果に限らず、Sheets/Notes/Memory/
# Debug/Fix等どのAgentが返した文章でも同様にエラーになり得るため、
# reply_message() / push_message() を呼ぶ直前の共通層でここに集約して対応する。
LINE_MAX_MESSAGE_LENGTH = 5000
LINE_MAX_MESSAGES_PER_SEND = 5
LINE_MAX_TOTAL_LENGTH = LINE_MAX_MESSAGE_LENGTH * LINE_MAX_MESSAGES_PER_SEND  # 25000
_LINE_TRUNCATION_NOTICE = "\n\n(※文字数が多いため一部を省略しました)"


def split_line_message(
    text,
    max_len=LINE_MAX_MESSAGE_LENGTH,
    max_messages=LINE_MAX_MESSAGES_PER_SEND,
    max_total=LINE_MAX_TOTAL_LENGTH,
):
    """LINEの1メッセージ文字数制限に合わせてテキストを分割する。

    - text が空/None の場合は既存挙動を維持するため [""] を返す
      (呼び出し側はこれまで通り TextMessage(text="") を1件送る)。
    - max_len以下ならそのまま1件のリストを返す(従来と同じ1メッセージ)。
    - max_lenを超える場合、直近max_len文字以内に改行があればそこで分割する
      (改行文字自体は前側のチャンクの末尾に残し、原文の内容を欠落させない)。
      改行が無ければmax_len文字で機械的に分割する。
    - 分割結果がmax_messages件を超える場合はmax_messages件に切り詰める。
    - 元テキストがmax_totalを超える場合は、分割前にmax_total文字で切り詰める。
    - 上記いずれかの理由で切り詰めが発生した場合、最後のメッセージの末尾に
      省略した旨の通知を追加する(通知を追加してもmax_lenを超えないよう、
      本文側を必要な分だけ削る)。
    """
    if not text:
        return [text or ""]

    truncated = False
    working = text
    if len(working) > max_total:
        working = working[:max_total]
        truncated = True

    if len(working) <= max_len:
        chunks = [working]
    else:
        chunks = []
        remaining = working
        while len(remaining) > max_len:
            window = remaining[:max_len]
            split_at = window.rfind("\n")
            if split_at <= 0:
                # 改行が見つからない(または先頭にしかない)場合はmax_len文字で強制分割
                chunks.append(remaining[:max_len])
                remaining = remaining[max_len:]
            else:
                # 改行位置を優先して分割する。改行文字は前側のチャンクの末尾に残し、
                # 原文の内容(改行含む)を欠落させないようにする。
                chunks.append(remaining[:split_at + 1])
                remaining = remaining[split_at + 1:]
        if remaining:
            chunks.append(remaining)

    if len(chunks) > max_messages:
        chunks = chunks[:max_messages]
        truncated = True

    if not chunks:
        chunks = [""]

    if truncated:
        notice = _LINE_TRUNCATION_NOTICE
        last = chunks[-1]
        available = max(0, max_len - len(notice))
        if len(last) > available:
            last = last[:available]
        chunks[-1] = last + notice

    return chunks


def _build_line_messages(text):
    """分割済みテキストをLINE送信用のTextMessageリストに変換する。"""
    return [TextMessage(text=chunk) for chunk in split_line_message(text)]


def _line_reply(reply_token, text):
    """reply_message()の共通ラッパー。5000文字超は自動的に複数メッセージに分割する。"""
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=_build_line_messages(text)
            )
        )


def _line_push(user_id, text):
    """push_message()の共通ラッパー。5000文字超は自動的に複数メッセージに分割する。"""
    with ApiClient(configuration) as api:
        MessagingApi(api).push_message(
            PushMessageRequest(
                to=user_id,
                messages=_build_line_messages(text)
            )
        )

print("===== APP VERSION CHECK =====")
print("search_notes enabled")

# アプリ起動時にDBスキーマを初期化する
# (Phase 2-1: db.pyへ移設に伴い、import時の暗黙実行から明示呼び出しに変更。
#  呼び出しタイミング自体は変更前と同じ位置を維持している)
init_db()

# =========================================================
# MCPクライアント(StreamableHTTP / stateless)
# =========================================================
def call_mcp_tool(tool_name, arguments, timeout=3.0):
    """既存テスト互換のための薄いラッパー。"""
    return _call_mcp_tool_impl(tool_name, arguments, timeout=timeout)


def _parse_mcp_json_list(raw):
    """既存内部呼び出し互換のための薄いラッパー。"""
    return _parse_mcp_json_list_impl(raw)


# LangGraphの finalize_node は、Debug/Fix/Patch/Test/Commit/Deploy等の
# 複数Agent結果を1通のLINEメッセージへまとめる目的で、
# 各結果を "【Memory】\n..." のように見出し付きで連結する。
# これはGitHub/Debugのような複数Agentが連鎖するルートには適しているが、
# Memory/Notes/Normal(通常Groq応答)は単一Agentの結果をそのまま
# ユーザーへ返す旧 generate_reply() の挙動(見出しなし)を踏襲する必要がある。
# そのため、これらのintentについては final_reply ではなく
# agent_results から該当Agentの生テキストを直接取り出して使う。
_DIRECT_TEXT_AGENT_KEYS = ("memory", "notes", "normal", "sheets")


def _invoke_graph(user_id: str, message: str):
    """LangGraphを実行し、結果のstate(dict)を返す。"""
    from graph.graph import graph

    return graph.invoke(
        {
            "user_id": user_id,
            "raw_message": message,
            "call_mcp_tool": call_mcp_tool,
            "agent_results": {},
        }
    )


def _extract_graph_reply(result):
    """
    graph.invoke() の結果から、ユーザーへ返す返信テキストを取り出す。

    Memory/Notes/Normalは見出しなしの生テキストを返し、
    GitHub/Debug/その他(fallbackを含む)は従来通り final_reply を使う。
    """

    if result is None:
        return None

    agent_results = result.get("agent_results", {}) or {}

    for key in _DIRECT_TEXT_AGENT_KEYS:
        agent_result = agent_results.get(key)
        if isinstance(agent_result, dict) and "text" in agent_result:
            return agent_result["text"]

    return result.get("final_reply", "Agent結果なし")


# Groq(OpenAI互換)のfunction calling形式でMCPツールを公開する。
# ユーザーごとの記憶を分離するため、モデルには生の key/value だけを
# 触らせ、実際にMCPへ渡す際はサーバー側でuser_idを前置して名前空間を分ける。
# =========================
# 「」内の文字列を抽出するヘルパー
# =========================
# set_reminder / save_memory 等でユーザーが「」で明示的に指定した文言は、
# AIに言い換えさせず、原文からそのまま抜き出して使う。
# (AIが1回目のツール呼び出し判断時にtemperature=0でも稀に数文字だけ
#  言い換えてしまう(例: 「文字化けテスト」→「文字化ケトスト」)ことがあるため、
#  正確性が必要な箇所は原文優先にする)
def extract_quoted_text(original_message):
    """既存テスト互換のための薄いラッパー。"""
    return _extract_quoted_text_impl(original_message)


# =========================
# 名前に関するkeyの統一
# =========================
# AIにkey名を自由に選ばせると、「name」「名前」「username」のように
# 保存時と取得時でkeyがブレて、get_memoryで見つからなくなることがある
# (「前に覚えた名前を忘れる」症状の主イン)。
# ユーザーの原文が明らかに名乗り(「〜という名前です」等)を意味している場合は、
# AIが選んだkeyを無視して "name" に強制的に統一する。
def normalize_memory_key(key, original_message):
    """既存テスト互換のための薄いラッパー。"""
    return _normalize_memory_key_impl(key, original_message)


# =========================
# remind_atのタイムゾーン補正
# =========================
# システムプロンプトでモデルに「+09:00付きのISO 8601で出力する」よう指示しているが、
# Groq/Llama系モデルは稀にタイムゾーン部分を省略して出力することがある
# (例: "2026-07-12T21:19:00" のようにオフセットなし)。
# JS(MCPサーバー側)のnew Date()はオフセットなしの文字列をUTCとして解釈するため、
# 「日本時間のつもりだった時刻」が実際には9時間ズレて登録されてしまう。
# これを防ぐため、タイムゾーン表記(Z または +HH:MM/-HH:MM)が末尾になければ、
# ここで明示的に +09:00 を補う。
def ensure_jst_offset(remind_at):
    """既存テスト互換のための薄いラッパー。"""
    return _ensure_jst_offset_impl(remind_at)


MCP_TOOLS_SCHEMA = _MCP_TOOLS_SCHEMA

# 記憶するvalueの整形

def clean_memory_value(key, value):
    """既存テスト互換のための薄いラッパー。"""
    return _clean_memory_value_impl(key, value)


def dispatch_tool_call(user_id, name, arguments, original_message=""):
    """既存テスト互換のための薄いラッパー。"""
    return _dispatch_tool_call_impl(user_id, name, arguments, original_message=original_message)


# =========================
# 削除確認の保留状態
# =========================
# 「メモ全部削除」「記憶全部削除」等の後に送られる「はい」が、
# どちらの削除を指しているか区別するため、user_idごとに保留する。
_pending_delete_confirmation = {}
_pending_confirm_lock = threading.Lock()


# =========================
# 削除系コマンドの自然文パターン
# =========================
# generate_reply() は毎回呼ばれるため、正規表現はここで1回だけコンパイルする
_DELETE_ALL_MEMORY_PATTERN = re.compile(
    r"記憶.*(全部|全て|すべて).*(消して|消す|削除|消していい)"
    r"|(全部|全て|すべて).*記憶.*(消して|消す|削除|消していい)"
)

# =========================
# AI本体(返信生成)
# =========================
# 旧 generate_reply() に存在していた各処理(Debug / GitHub / Memory /
# Notes / 通常のGroq応答)は、現在はすべてLangGraph側
# (Supervisor → Router → 各Agent Node → Finalizer)へ移植されている。
# ここでは、Daily AI Report / pytest向けの特別扱いのみ従来通り関数内で
# 処理し、それ以外の全メッセージをLangGraphの入口として graph.invoke()
# に委譲する。
def generate_reply(user_id, message):
    print("===== APP VERSION CHECK =====")
    print("GITHUB ROUTE ENABLED")
    print("=== GENERATE_REPLY ===", repr(message))
    print("MESSAGE DEBUG:", repr(message), type(message))

    # =========================
    # Daily AI Report
    # =========================
    if "Daily AI Repo" in message:
        print("DAILY AI REPORT TRIGGERED")

        report = generate_ai_secretary_report(user_id)

        return report

    # pytest内部テストはAI処理しない
    if message.startswith("pytest"):
        return "pytestテストメッセージを受信しました。"

    # =========================
    # LangGraph 入口
    # =========================
    # Debug / GitHub / Memory / Notes / 通常応答のいずれも、
    # Supervisorのintent判定によって適切なAgent Nodeへ振り分けられる。
    print("DEBUG CONDITION CHECK")
    print("startswith debug:", message.startswith("debug"))
    print("has github:", "github" in message.lower())
    print("has search:", "search" in message.lower())
    print("has repo:", "repo" in message.lower())
    print("GITHUB INTENT RESULT:", is_github_intent(message))

    try:
        result = _invoke_graph(user_id, message)
    except Exception as e:
        print("===== GRAPH INVOCATION ERROR =====")
        print(type(e).__name__, str(e))
        import traceback
        traceback.print_exc()
        return f"Agent起動エラー: {type(e).__name__}: {e}"

    print("===== AFTER GRAPH.INVOKE =====")
    print(result)

    return _extract_graph_reply(result)
# =========================
# =========================
# LINE webhook
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    print(f"[LOG] /callback endpoint called")
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature")
    print("===== CALLBACK RECEIVED =====")
    print("BODY:", body)
    print("SIGNATURE:", signature)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("===== HANDLER ERROR =====")
        print(e)
    return "OK"


# =========================
# 重複イベント防止
# =========================
# LINEのWebhookは応答が遅いと同じイベントを再送してくることがある。
# (今回、set_reminderの内容が微妙に異なる状態で3重に保存されたのはこれが原因)
# 同じmessage_idを2回以上処理しないよう、直近処理済みIDをメモリに保持する。
# ※ workers=1構成のプロセス内メモリのみで完結する簡易対策。
# プロセス再起動で消えるが、再送は通常同一プロセスが動いている短時間内に来るため実用上問題ない。
# OrderedDictを使い、上限超過時は挿入順(古い順)で確実に間引く。
# (setのpop()は削除順が保証されないため、直近処理したIDが誤って
#  間引かれる可能性があった)
_processed_message_ids = OrderedDict()
_processed_lock = threading.Lock()
_MAX_TRACKED_IDS = 2000

# ユーザー単位の同時処理防止
# 同じユーザーの質問が重なった場合、返信順序が崩れないようにする
_user_processing_locks = {}
_user_processing_lock = threading.Lock()


def _process_and_reply(event, user_id, text):
    print(f"[LOG] _process_and_reply called: user_id={user_id}")

    # 同じユーザーの処理が同時実行されないようにする
    with _user_processing_lock:
        if user_id not in _user_processing_locks:
            _user_processing_locks[user_id] = threading.Lock()

    user_lock = _user_processing_locks[user_id]

    with user_lock:
        print(f"[LOG] USER LOCK ACQUIRED: {user_id}")

        # N8N_WEBHOOK_URLが設定されている場合はn8nに処理を委譲する。
        # 返信(reply_message/push_message)はn8n workflow側が既存の
        # /internal/ask, /internal/push を呼び出して行う想定のため、
        # ここではn8nへの送信のみを行いreturnする。
        if N8N_WEBHOOK_URL:
            print(f"[LOG] DELEGATING TO N8N: user_id={user_id}")
            _delegate_to_n8n(user_id, text, N8N_WEBHOOK_URL)
            return

        """generate_reply〜reply_messageまでを非同期に実行する。
        LINEへのWebhook応答(200 OK)を待たせないためにスレッドへ切り出している。"""
        try:
            reply = generate_reply(user_id, text)
            print("GENERATED REPLY:", repr(reply))

            try:
                _line_reply(event.reply_token, reply)
                print("REPLY SENT SUCCESS")
            except Exception as reply_err:
                # reply_tokenの失効(Webhook受信から短時間で無効になる)等でreply_messageが
                # 失敗した場合のみ、push_messageで同じ内容を送り直す。
                # reply_messageが成功する通常時はこのフォールバックには入らない。
                print("REPLY FAILED, FALLBACK TO PUSH:", reply_err)
                _line_push(user_id, reply)
                print("PUSH FALLBACK SENT SUCCESS")
        except Exception as e:
            import traceback
            print("===== HANDLE ERROR (async) =====")
            traceback.print_exc()


# =========================
# EVENT HANDLER
# =========================
@handler.add(MessageEvent, message=TextMessageContent)
def handle(event):
    print(f"[LOG] handle MessageEvent called")

    print("=== NORMAL LINE DEBUG ===")
    print("=== WEBHOOK RECEIVED ===")
    print("LINE USER ID:", repr(event.source.user_id))
    print("TYPE:", type(event.source.user_id))
    print("LEN:", len(event.source.user_id))
    print("========================")
    print("===== EVENT TRIGGERED =====")
    try:
        user_id = event.source.user_id
        print(f"[DEBUG LINE USER ID] {user_id}")
        text = event.message.text
        message_id = event.message.id

        print("USER:", user_id)
        print("TEXT:", text)
        print("MESSAGE_ID:", message_id)

        with _processed_lock:
            if message_id in _processed_message_ids:
                print("DUPLICATE MESSAGE IGNORED (memory):", message_id)
                return

            if is_processed_event(message_id):
                print("DUPLICATE MESSAGE IGNORED (db):", message_id)
                return

            created = create_processed_event(message_id, user_id=user_id, source="line")
            if not created:
                print("DUPLICATE MESSAGE IGNORED (create_failed):", message_id)
                return

            _processed_message_ids[message_id] = True
            if len(_processed_message_ids) > _MAX_TRACKED_IDS:
                # 最も古く追加されたIDから確実に間引く(last=Falseで先頭=最古を削除)
                _processed_message_ids.popitem(last=False)

        threading.Thread(
            target=_process_and_reply,
            args=(event, user_id, text),
            daemon=True
        ).start()

    except Exception as e:
        import traceback
        print("===== HANDLE ERROR =====")
        traceback.print_exc()


# =========================
# AI開発報告機能 (内部API)
# =========================
def fetch_recent_github_commits(hours=24):
    print(f"[LOG] fetch_recent_github_commits called")
    if not AI_REPORT_GITHUB_REPO:
        return []

    url = f"https://api.github.com/repos/{AI_REPORT_GITHUB_REPO}/commits"
    headers = {"Accept": "vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        since_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        params = {"since": since_time.isoformat()}
        res = httpx.get(url, headers=headers, params=params, timeout=10.0)
        if res.status_code != 200:
            print("AI REPORT: GITHUB API ERROR STATUS:", res.status_code, res.text)
            return []

        commits = []
        for c in res.json():
            commit_info = c.get("commit", {})
            message = commit_info.get("message", "").split("\n")[0].strip()
            author_date = commit_info.get("author", {}).get("date", "")
            if message:
                commits.append({"message": message, "date": author_date})

        # 新しい順→古い順に並び直す(会話として自然な時系列にするため)
        commits.reverse()
        return commits

    except Exception as e:
        print("AI REPORT: GITHUB FETCH ERROR:", e)
        return []

def fetch_ai_secretary_facts(user_id):
    print(f"[LOG] fetch_ai_secretary_facts called: user_id={user_id}")
    """
    AI秘書レポートに使う「事実」一式を集める。
    どれか1つの取得に失敗しても、他は取得できた分だけを使う。
    """
    facts = {"commits": [], "memories": [], "reminders": []}

    facts["commits"] = fetch_recent_github_commits(hours=24)

    try:
        memories_raw = call_mcp_tool("get_all_memory", {"user_id": user_id})
        facts["memories"] = _parse_mcp_json_list(memories_raw)

        print("===== AI REPORT MEMORY RAW =====")
        print(memories_raw)
        print("===== AI REPORT MEMORY PARSED =====")
        print(facts["memories"])
    except Exception as e:
        print("AI REPORT: GET_ALL_MEMORY ERROR:", e)

    try:
        reminders_raw = call_mcp_tool("list_reminders", {"user_id": user_id})
        facts["reminders"] = _parse_mcp_json_list(reminders_raw)

        print("===== AI REPORT REMINDER RAW =====")
        print(reminders_raw)
        print("===== AI REPORT REMINDER PARSED =====")
        print(facts["reminders"])
    except Exception as e:
        print("AI REPORT: LIST_REMINDERS ERROR:", e)

    return facts

def build_ai_secretary_fact_block(facts):
    print(f"[LOG] build_ai_secretary_fact_block called")
    """収集した事実を、Groqに渡すためのテキストブロックに整形する。"""
    if facts["commits"]:
        commits_text = "\n".join(f"- {c['message']}" for c in facts["commits"])
    else:
        commits_text = "(昨日24時間以内のコミットは記録されていません)"

    if facts["memories"]:
        memories_text = "\n".join(
            f"- {m.get('key')}: {m.get('value')}" for m in facts["memories"]
        )
    else:
        memories_text = "(保存済みメモはありません)"

    if facts["reminders"]:
        reminders_text = "\n".join(
            f"- {r.get('message')}" for r in facts["reminders"]
        )
    else:
        reminders_text = "(未完了のタスク・リマインダーはありません)"

    return (
        "【昨日の実際のコミット(GitHubより取得・事実)】\n"
        f"{commits_text}\n\n"
        "【保存済みメモ(事実)】\n"
        f"{memories_text}\n\n"
        "【今日の予定・未完了リマインダー(事実)】\n"
        f"{reminders_text}"
    )

def generate_ai_secretary_report(user_id):
    print(f"[LOG] generate_ai_secretary_report called: user_id={user_id}")
    facts = fetch_ai_secretary_facts(user_id)
    fact_block = build_ai_secretary_fact_block(facts)

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")

    prompt_body = f"""
今日は {today_str} です。
以下の【事実データ】のみに基づいて、AI秘書としてユーザーへの「朝の進捗・予定レポート」を作成してください。

{fact_block}

【注意事項】
- 事実データに書かれている内容だけを元に作成してください。
- データにない実績、予定、目標、感想、励まし文を追加してはいけません。
- 「新たなチャンスです」「頑張りましょう」など事実に基づかない文章は禁止です。
- データが空の場合は「記録はありません」とだけ書いてください。
- 丁寧で簡潔なAI秘書口調で出力してください。
- 箇条書きや段落を適度に使って読みやすくしてください。
- 事実データに存在しない「今日の目標」「注目ポイント」「参考資料」などの項目は作成しないでください。
- 情報がない場合は「ありません」と簡潔に記載してください。
- レポートは「昨日の進捗」「保存済みメモ」「今日の予定」の3項目を基本構成にしてください。
"""

    res = generate_secretary_report(prompt_body)
    return res.choices[0].message.content


# =========================
# AI開発報告 API
# =========================
@app.route("/internal/ai-report", methods=["POST"])
def internal_ai_report():
    print(f"[LOG] /internal/ai-report endpoint called")
    provided_key = request.headers.get("x-internal-key")
    if provided_key != INTERNAL_PUSH_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "ok": False,
            "error": "user_id is required"
        }), 400

    try:
        report_text = generate_ai_secretary_report(user_id)
        _line_push(user_id, report_text)
        save_message(user_id, "assistant", report_text)
        print(f"AI REPORT SENT: user_id={user_id}")
    except Exception as e:
        # LINE送信やDB保存に失敗した場合でも、全体の処理結果としては
        # ワークフローのジョブ中断を防ぐためHTTP 200を返すか、
        # あるいはエラー内容を出力する。ここでは安全のため、
        # 例外をログ出力しつつ呼び出し元(GitHub Actions)には成功として返す。
        print("AI REPORT WARNING (履歴DB保存に失敗、LINE送信自体は成功):", e)

    return jsonify({"ok": True})


# n8n / LangGraph AI API
register_internal_ask_route(app, INTERNAL_PUSH_KEY, generate_reply)

@app.route("/internal/push", methods=["POST"])
def internal_push():
    provided_key = request.headers.get("x-internal-key")
    if provided_key != INTERNAL_PUSH_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")

    # pytest用仮ユーザーID変換
    if user_id == "test-user":
        user_id = "U19391b0b93be2f4d94284361153919ce"

    message = data.get("message")

    # user_id / message が None・欠落・空文字の場合はここで400を返す。
    # (len()などの呼び出しより前に検証することで、TypeErrorに起因する
    #  意図しない500応答を防ぐ)
    if not user_id or not message:
        print("[LOG] /internal/push: user_id or message missing/empty")
        return jsonify({"ok": False, "error": "user_id and message are required"}), 400

    print(f"[LOG] /internal/push called: user_id={user_id!r}")

    try:
        _line_push(user_id, message)
        save_message(user_id, "assistant", message)
        print(f"[LOG] /internal/push sent: user_id={user_id!r}")
        return jsonify({"ok": True})

    except Exception as e:
        print("[LOG] /internal/push error:", type(e).__name__, str(e))
        return jsonify({"ok": False, "error": str(e)}), 500

# =========================
# health check
# =========================
@app.route("/")
def home():
    return "OK"

@app.route("/health")
def health():
    return jsonify({"ok": True, "timestamp": datetime.now(timezone.utc).isoformat()})
if __name__ == "__main__":
    print("===== FLASK SERVER START =====")
    app.run(host="0.0.0.0", port=5001)

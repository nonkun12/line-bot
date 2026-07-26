import os
from dotenv import load_dotenv
from linebot.v3.messaging import Configuration
from linebot.v3.webhook import WebhookHandler
from groq import Groq

load_dotenv()

# =========================
# ENV
# =========================
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# MCPサーバー(Render上のmy-mcp-server)のURL。
# 例: https://my-mcp-server.onrender.com/mcp
MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]

# MCPサーバー側のrequireApiKeyと照合される固定キー。
# my-mcp-server側の環境変数 MCP_API_KEY と同じ値をここに設定する。
MCP_API_KEY = os.environ["MCP_API_KEY"]

# MCPサーバー(スケジューラー)がリマインダー送信を依頼してくる際に
# このLINE Bot側の /internal/push エンドポイントを叩く。
# その時に付けてくるヘッダー "x-internal-key" と照合する値。
# my-mcp-server側の環境変数 INTERNAL_PUSH_KEY と同じ値をここに設定する。
INTERNAL_PUSH_KEY = os.environ["INTERNAL_PUSH_KEY"]

# AI秘書レポートで「昨日の実際のコミット」を取得する対象リポジトリ。
# GITHUB_TOKENは必須ではない(公開リポジトリなら未認証でも取得可)が、
# レート制限回避のためread-onlyのPATを設定することを推奨。
AI_REPORT_GITHUB_REPO = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
# timeoutを明示的に指定し、Groq側が詰まってもgunicorn workerごと
# ハングしないようにする(Renderがクラッシュと誤認して再起動する原因になっていた)
client = Groq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)

MODEL = "llama-3.1-8b-instant"
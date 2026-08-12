# LINE AI Secretary

LINE Bot + MCP (Model Context Protocol) + LangGraph を組み合わせたマルチエージェント型 AI 秘書システム。
LINE から自然言語でメッセージを送信することで、システム背後で連携する各種エージェントが動作し、スプレッドシートの操作、GitHub の参照、メモの作成、記憶の管理、自動デバッグおよびデプロイなどを実行します。

---

## 1. システム構成

本システムは **LangGraph** を用いた状態遷移グラフ（StateGraph）で構築されており、メッセージ受信から返信生成までの一連の処理は以下のように制御されます。

```
                    LINE Webhook 受信
                           ↓
                       START 
                           ↓
                      Supervisor 
                           ↓ (分類: Routing)
       +-------------------+-------------------+-------------------+
       |                   |                   |                   |
  Sheets Agent       GitHub Agent         Notes Agent        Memory Agent ...
       |                   |                   |                   |
       +-------------------+-------------------+-------------------+
                           ↓
                       Finalizer (最終応答のフォーマット & 結合)
                           ↓
                          END
```

1. **LINE Webhook 受信**: ユーザーからのLINEメッセージを非同期スレッドに引き渡し、グラフを実行します。
2. **Supervisor**: ユーザーの自然言語メッセージからインテント（意図）を分類します。
3. **Conditional Router**: 分類されたインテントに基づいて、対応する適切なエージェントノードへと処理を分岐します。
4. **各 Agent Node**: 各自の責務に応じて処理（DB操作、MCP接続、外部API呼び出しなど）を行い、結果を状態（State）に記録します。
5. **Finalizer**: エージェントたちの処理結果をまとめ、LINE送信向けにフォーマットを整えます。

---

## 2. 実装済み Agent

各エージェントは、自然言語による表現からパラメータを抽出し、以下のような実動作を行います。

### 📊 Google Sheets Agent
Google スプレッドシート（設定されたシートID）に対する操作を行います。
*   **読み取り・検索**: シート内のテキストを走査し、関連する情報を探します。
*   **行追加（記録）**: 「シートに記録：〜〜」「シートに〜〜を追加して」といった表現から情報を抽出し、新規行を追加します。
*   **行削除**: 「シートから〜〜を削除して」などのキーワード指定によって、該当する行を削除します。
*   **AI分析**: 「シートの内容を分析して」「シートの内容を要約して」といった自然言語の指示受け、シートの全行を読み出してAIがデータの集計や特徴分析、要約回答を行います。

### 🐙 GitHub Agent
連携する GitHub リポジトリ（`AI_REPORT_GITHUB_REPO` 等）の操作や確認を行います。
*   **リポジトリ・コミット情報の取得**: コミット履歴（最新5件など）、PR、Issueのステータスを取得します。
*   **ファイル内容の取得**: 「README.mdを見せて」「app.pyを表示して」などの自然言語指示、または「github file <path>」という明示的コマンドから、リポジトリ内のコードやドキュメントを読み出して表示します。

### 📝 Notes Agent
データベース（SQLite）を使用したシンプルなノート（メモ）の管理を行います。
*   **保存**: メモの新規作成。
*   **一覧表示**: 保存されているメモを一覧で返します。
*   **検索**: メモのタイトルや本文から、キーワードおよび自然言語ベースでの曖昧検索を行います。
*   **自動保存 (Auto Save)**: 会話の中で「〜〜とメモしておいて」といったパターンを抽出し、自動でノートに分類して書き込みます。
*   **削除**: 保存したメモの削除。

### 🧠 Memory Agent
**MCP (Model Context Protocol)** 経由でメモリサーバーに接続し、ユーザーごとのコンテキストや個別設定を記憶・想起します。
*   **名前空間の分離**: LINEの `user_id` ごとに個別の記憶空間（Namespace）を確保します。
*   **記憶の保存**: 「私の名前は nonkun です」「好きな食べ物はリンゴと覚えて」などの会話からキーと値を抽出し、MCPサーバーの `save_memory` に保存します。
*   **記憶の削除**: 「〜〜を忘れて」「記憶を消して」などの指示により `delete_memory` を呼び出します。
*   また、曖昧なキーによる検索を防止するための「キーの標準化（`name` への統一等）」や「値の整形」処理が自動で適用されます。

### 💬 Normal Agent
特別な指示や意図（Sheets、GitHub、Notes、Memory等）に該当しない汎用的なテキストに対して、Groq等のLLMを使用して日常会話や雑談のテキストを生成し返答します。

---

## 3. AI Debug / Fix / Deploy パイプライン

本システムは、エラーログを自動検知して修正・検証・デプロイまで行う先進的な自己デバッグ・パイプラインを搭載しています。
このフローは、以下のエージェントとノードが順番に遷移することで安全に実行されます。

```
Debug Agent ➔ Fix Agent ➔ Patch Generate ➔ Patch Apply ➔ Test Agent ➔ Commit Agent ➔ Deploy Agent
```

1. **Debug Agent**: 実行時に起きた例外やログを収集し、エラーの根本原因を分析します。
2. **Fix Agent**: 修正コードの提案を作成します。
3. **Patch Generate Agent**: Fix Agentの提案から、検証可能な統一デフ（Unified Diff）を生成します。
4. **Patch Apply Agent (パッチ適用)**: 生成されたパッチを適用します。
5. **Test Agent**: 修正後の状態で `pytest` を実行し、デバッグ結果の正常性を検証します。
6. **Commit Agent**: テストが正常に **PASS した場合のみ**、修正内容を Git にコミットします。
7. **Deploy Agent**: コミット成功後、Render APIを叩いて最新コードを本番環境へデプロイします。

### ⚠️ 安全性のための制御フラグ
自動修正・コミット・デプロイによる予期せぬ破壊を防ぐため、以下の環境変数による安全ゲート（デフォルトはすべて `false`）を設けています。明示的に有効化しない限り、破壊的な操作は実行されません。

| 環境変数名 | デフォルト値 | 挙動 |
| :--- | :---: | :--- |
| `AUTO_APPLY_PATCH` | `false` | `false` の時はパッチの自動適用を行わず、提案（Diff）の出力に留めます。`true` の場合、`git apply --check` による整合性検証を経て、一時的な退避用ブランチ (`fix/auto-<uuid>`) 上でパッチを適用します（稼働ブランチに直接書き込みません）。 |
| `AUTO_DEPLOY` | `false` | `false` の時は Render へのデプロイを行わず「デプロイ保留中」として処理を終えます。`true` の場合、コミット完了後に Render のデプロイエンドポイントを叩いてデプロイを走らせます。 |
| `RENDER_API_KEY` | - | `AUTO_DEPLOY=true` の場合に必須となる Render API キー。 |
| `REPO_WORKDIR` | (カレントディレクトリ) | パッチ適用やテスト実行、コミットを行うGitローカル作業ディレクトリのパス。 |

---

## 4. LINE メッセージの送信処理 (文字数制限対応)

LINE Messaging API には「1メッセージあたり最大5000文字」「1回の応答あたり最大5メッセージ（合計25000文字）」という文字数制限が存在し、これを超えると送信エラー (HTTP 400) になります。
本システムでは、すべてのエージェントの応答結果を LINE API に渡す直前の共通ラッパー層で自動処理します。

*   **長文分割**: 5000文字を超える長文の場合、直近の「改行文字 (`\n`)」を探して文脈を壊さないように段落単位でテキストを分割（最大5メッセージ分まで）します。
*   **自動切り詰めと通知**: 5メッセージ（合計25000文字）を超える極端な長文（GitHubの長いファイルの中身など）の場合、末尾に `\n\n(※文字数が多いため一部を省略しました)` という注記を安全に差し込み、文字数が超過しないよう後ろ側を自動的に切り詰めます。

---

## 5. その他の機能

*   **Daily AI Report (秘書日報)**
    *   メッセージ内に `Daily AI Repo` などのトリガーワードが含まれている場合、過去24時間以内の「GitHubコミット履歴」「Memoryに保存されたデータ」「未完了のリマインダーやタスク」を自動収集し、整理された秘書レポートとして合成・配信します。
*   **LINE Webhook 重複イベント防止**
    *   LINEプラットフォームからのWebhookは、応答遅延時に全く同じイベントが再送される仕様になっています。
    *   システムでは、直近2000件のイベントIDをメモリキャッシュ (`OrderedDict`) に保持し、さらに SQLite データベースの `processed_events` テーブルにイベント履歴を記録することで、リマインダーやメッセージの多重処理・多重送信を防ぎます。

---

## 6. セットアップ

### 必要条件
*   Python 3.13 以上
*   SQLite3

### 手順
1. **リポジトリのクローン & 仮想環境の構築**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **環境変数の設定**
   `.env` ファイルを作成し、以下の変数を定義します。
   ```env
   # LINE Bot 設定 (必須)
   CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
   CHANNEL_SECRET=your_line_channel_secret

   # AI / LLM (必須)
   GROQ_API_KEY=your_groq_api_key

   # MCP (Memory & Reminders, 必須)
   MCP_SERVER_URL=https://your-mcp-server/mcp
   MCP_API_KEY=your_mcp_api_key
   INTERNAL_PUSH_KEY=your_internal_push_key

   # Google Sheets Agent (必須)
   GOOGLE_SHEETS_SPREADSHEET_ID=your_google_sheets_spreadsheet_id
   # 以下のいずれか一方 (または両方) で Google の認証情報を指定します
   GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON=your_google_service_account_credentials_json_string
   GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE=path/to/your/credentials.json

   # GitHub Agent (任意)
   AI_REPORT_GITHUB_REPO=nonkun12/line-bot
   GITHUB_TOKEN=your_github_pat_token
   ```

3. **ローカルサーバーの起動**
   ```bash
   python3 app.py
   ```

---

## 7. テスト

テストスイートは `pytest` を使用して構成されています。

```bash
# 基本的なテストの実行 (静かな出力)
pytest -q

# もしくは仮想環境内の pytest を直接実行する場合
venv/bin/pytest -q
```

> [!NOTE]
> 2026-08-12 時点において、Mac (Apple Silicon / ARM64) 環境にて `arch -arm64 venv/bin/pytest -q` 経由でテストが正常にパスすることを確認実績として有しています。

---

## 8. ロードマップ

### 実装済み (Phase 1 〜 4c)
*   [x] LangGraph による Supervisor/Router のエージェント構造
*   [x] 各種エージェント (Google Sheets, GitHub, Notes, Memory, Normal) の実装
*   [x] 自動デバッグ、パッチ生成、テスト実行、自動コミット、Renderデプロイパイプラインの構築
*   [x] LINE 向けメッセージ自動分割・切り詰めレイヤーの追加

### 今後の実装予定
*   [ ] AI生成コードの品質自動チェック（`slopguard` 等の検証ツールとの連携）
*   [ ] 各エージェントによる対応インテントや操作コマンドのさらなる拡充

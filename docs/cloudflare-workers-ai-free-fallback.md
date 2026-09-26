# Cloudflare Workers AI Free フォールバック設計

## 目的

LINE Bot の通常会話生成に、Cloudflare Workers AI を第3の生成プロバイダとして追加できるようにする。

今回の変更では **接続・API key 発行・本番有効化は行わない**。本書は後日の実装時にそのまま使える設計を固定するためのもの。

## 想定するプロバイダ順

通常系の生成は次の順序を基本とする。

```text
Gemini
  ↓ 一時障害 / rate limit / timeout / 5xx
Groq
  ↓ 一時障害 / rate limit / timeout / 5xx
Cloudflare Workers AI Free
  ↓ 利用不能 / 無料枠到達 / timeout / 5xx
安全な停止応答
```

重要:

- Cloudflare は Gemini/Groq の「復旧待ち中」にだけ使う第3経路として扱う。
- Gemini/Groq が復旧したら、次回リクエストから自動的に上位経路へ復帰する。
- すべてのプロバイダが利用不能なら処理を継続せず、fail-closed で停止する。
- 自動課金への切り替えをしない。

## Cloudflare 側の無料枠ガード

Cloudflare Workers AI の Free allocation を超えた場合に処理を継続しない設計にする。

実装時の原則:

1. Workers AI Free で利用可能と確認済みのモデルだけを allowlist にする。
2. 有料モデル名を環境変数で自由入力できる設計にはしない。
3. Free-only モードを boolean ではなく、コード側の固定 allowlist と環境設定の二重チェックで守る。
4. Cloudflare API が quota/usage exceeded 等を返した場合は Cloudflare provider を一時 unavailable として扱う。
5. Cloudflare 側で有料プランの Unified Billing を利用する経路は採用しない。
6. API key / token はリポジトリ、ログ、LINE応答、Google Sheets に記録しない。

## 想定環境変数

API key 発行時に、以下を追加する。

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_AI_TOKEN
```

モデル指定は本番運用時には固定 allowlist から選ぶ。設計上の既定候補は:

```text
@cf/zai-org/glm-4.7-flash
```

モデルの無料対象状況は、実装・有効化時点で Cloudflare 公式のモデル別料金表を再確認する。

## Provider インターフェース

既存の Gemini/Groq failover と同じ概念で、Cloudflare を独立 provider として扱う。

概念 API:

```python
class CloudflareWorkersAIProvider:
    def generate(
        self,
        *,
        message: str,
        user_id: str,
        request_id: str,
    ) -> str:
        ...
```

provider 層は以下だけを担当する。

- Cloudflare API の HTTP 呼び出し
- timeout の制御
- HTTP エラーの provider-level error への変換
- 空応答 / 不正応答の拒否
- usage/quota exceeded の検出

通常会話、メモリ、MCP、LINE reply のロジックは provider 層に持ち込まない。

## Failover 状態

既存の `ProviderFailover` を拡張し、次の3 providerを管理する。

```text
gemini
groq
cloudflare_workers_ai
```

状態:

- available
- unavailable_until
- failure reason（ログ用。秘密情報は禁止）

基本動作:

- 成功: provider を available に戻す
- 一時障害: cooldown を設定
- cooldown 経過後: 自動再試行対象へ復帰
- quota exceeded: より長い cooldown または当日停止を検討
- 全経路 unavailable: 安全停止

## Quota / 課金安全策

「無料のつもりで有料になる」事故を避けるため、実装時に次を必須とする。

- Free-safe model allowlist
- Cloudflare Unified Billing を利用しない
- timeout と出力長上限
- 1リクエスト1試行
- プロバイダ間の無制限リトライ禁止
- quota exceeded 時の fail-closed
- API token の最小権限化
- provider の復旧判定は実際の成功レスポンスで行う

## メモリとの関係

通常会話では現在のメモリ取得を先に行う既存設計を維持する。

- Cloudflare fallback だからといって memory を無視しない。
- memory service failure と LLM provider failure を混同しない。
- memory 取得失敗時に「記憶がない」と推測してはいけない。
- provider 切替で user_id を LLM 側へ不要に露出させない。

## ログ / Google Sheets

監査ログには次のような非機密情報だけを記録する。

```text
request_id
provider
success/failure
failure_category
cooldown action
final provider
overall result
```

記録してはいけないもの:

- API token
- Authorization header
- ユーザーの秘密情報
- provider の生レスポンス全文

Google Sheets への記録は既存の autonomous ledger の安全策に従い、実際の実行結果・最終ゲート結果を記録する。

## テスト設計

実装時に最低限、次を追加する。

1. Gemini 成功 → Gemini のみで終了
2. Gemini 失敗 → Groq 成功
3. Gemini/Groq 失敗 → Cloudflare 成功
4. 3 provider 全失敗 → 安全停止
5. Gemini cooldown 経過後に自動復帰
6. Groq cooldown 経過後に自動復帰
7. Cloudflare cooldown 経過後に自動復帰
8. Cloudflare quota exceeded → 自動継続しない
9. 有料モデル名を指定 → fail-closed
10. timeout → provider failure
11. HTTP 5xx / 429 → provider failure
12. 空 / 不正JSON応答 → provider failure
13. API token がログやSheetsに出ない
14. provider 切替後も memory コンテキストが壊れない
15. 1リクエスト内で同一providerを無限再試行しない

## 本番有効化の順序

後日 API key を発行するときは、次の段階で進める。

```text
1. Cloudflare アカウント / API token 発行
2. Account ID と token を Render/GitHub Secrets に登録
3. Free-safe model allowlist を確認
4. 隔離された接続テスト
5. provider 単体テスト
6. failover 統合テスト
7. safety gate / CI
8. 本番では最初は明示的に有効化
9. 実測ログ確認
10. 問題なければ通常の第3 fallback として運用
```

API key 発行前は、Cloudflare provider を **disabled by missing credentials** とし、既存の Gemini/Groq 動作には影響させない。

## 非目標

今回の設計では以下を行わない。

- OpenRouter の導入
- Cloudflare Worker 自体のデプロイ
- API key の発行
- API key のコミット
- 課金プランへの自動変更
- 自動 merge / deploy
- LINE/Slack への新しい管理コマンド追加

## 完了条件

この設計の実装を開始できる状態は、以下を満たした時点とする。

- provider 順序が固定されている
- Free-only ガード方針が固定されている
- failover / recovery 方針が固定されている
- quota 超過時の停止方針が固定されている
- API key は未設定のまま
- 既存 Gemini/Groq の動作を変更しない

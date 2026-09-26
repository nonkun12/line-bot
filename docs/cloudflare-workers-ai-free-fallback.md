# Cloudflare Workers AI Free 将来候補設計

## 位置づけ

Cloudflare Workers AI は、**現在の本番フォールバック経路には入れない**。

現在の運用は次の2系統だけとする。

```text
Gemini
  ↓ 一時障害 / rate limit / timeout / 5xx
Groq
  ↓ 利用不能
安全に停止
```

この Gemini → Groq のフェイルオーバーを、リクエストごとに繰り返す。
各プロバイダは cooldown 後に復旧確認対象へ戻し、復旧が確認できれば次回リクエストから再利用する。

**Gemini と Groq が両方とも利用できない場合は、追加プロバイダへ進まず停止する。**

Cloudflare は、将来必要になった場合に追加検討できる「第3候補」として設計資料だけを保持する。

## 今回やらないこと

- Cloudflare を Gemini/Groq の代替経路へ追加しない
- Cloudflare API を呼び出さない
- API key / token を発行・登録しない
- Render / GitHub Secrets に Cloudflare 資格情報を追加しない
- Cloudflare Worker をデプロイしない
- 既存の Gemini/Groq failover 実装を変更しない

## 将来の導入時に固定する安全条件

Cloudflare を将来追加する場合も、ユーザーの明示的な方針変更なしに既存の停止条件を変更しない。

### 無料利用のガード

1. Cloudflare Workers AI Free で利用可能なモデルだけをコード側 allowlist にする。
2. モデル名を環境変数から自由指定できるようにしない。
3. Free allocation 超過時は処理を継続しない。
4. 課金側へ自動的に切り替わる経路を使わない。
5. Cloudflare Unified Billing を現在の設計には組み込まない。
6. API token はリポジトリ、ログ、LINE応答、Google Sheetsへ出さない。

### 想定環境変数

将来接続するときの候補:

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_AI_TOKEN
```

Free対象モデルは、その時点の Cloudflare 公式料金・モデル一覧を再確認して固定する。

## 将来の Provider インターフェース案

現在の本番経路には接続しないが、実装する場合は既存 provider と分離する。

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

担当範囲:

- Cloudflare API 呼び出し
- timeout
- HTTPエラーの分類
- 空応答 / 不正応答の拒否
- quota / usage exceeded の検出

メモリ、MCP、LINE reply、開発実行権限などは持たせない。

## 将来の failover 案

Cloudflare を本番経路へ加えることを決めた場合でも、次の設計変更を明示的に承認してから実装する。

```text
現在:
Gemini → Groq → 停止

将来承認後のみ:
Gemini → Groq → Cloudflare → 停止
```

つまり、**現在の「Gemini と Groq の両方がダメなら停止」という安全条件を、Cloudflare設計だけでは変更しない。**

## 復旧

現在の本番運用では:

- Gemini 成功 → Gemini を利用
- Gemini 失敗 → Groq を試行
- Groq 成功 → Groq を利用
- Gemini/Groq 両方失敗 → 停止
- cooldown 経過後 → 復旧確認を行い、成功した provider を再利用

Cloudflare はこの復旧ループにも参加させない。

## テスト方針

現在の本番テスト対象:

1. Gemini 成功
2. Gemini 失敗 → Groq 成功
3. Gemini/Groq 両方失敗 → 安全停止
4. Gemini cooldown 後の復旧
5. Groq cooldown 後の復旧
6. 1リクエスト内で同一providerを無限再試行しない
7. provider 切替時もメモリ連携を壊さない

将来 Cloudflare を有効化するときに初めて追加するテスト:

- Cloudflare 単体接続
- Free-safe model allowlist
- quota exceeded → 停止
- 有料モデル指定 → fail-closed
- timeout / 429 / 5xx / 不正JSON
- token 漏えい防止
- 3系統 failover

## API key 発行後の手順（将来）

API key を発行しただけでは本番経路に入れない。

```text
1. 資格情報を安全に登録
2. Cloudflare 単体の隔離テスト
3. Free対象モデルを公式情報で再確認
4. 単体テスト
5. failover 統合テスト
6. Safety Gate / CI
7. 明示的な本番有効化判断
```

## 完了状態

このドキュメントの役割は「Cloudflare を今は使わないまま、将来の追加条件を固定しておくこと」。

**現時点の本番運用ルールは Gemini → Groq を繰り返し、両方ダメなら停止。**

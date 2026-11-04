# 星を拾った夜 — Muse型サイドチャット連携設計

## 目的

将来、LINE AI Secretary / Web UIにMuse型のサイドチャットを実装するとき、この作品を最初の統合プロジェクトとして利用できるようにする。現時点では独立会話の保存基盤（PR #1272）と作品データを疎結合に保ち、特定UIや特定モデルに依存させない。

## 会話モデル

各サイドチャットは独立した履歴と目的を持つ。プロジェクトID `STAR-NIGHT` を共有し、共通設定資料・ストーリーグラフを必要に応じて参照する。

| Workspace ID | 表示名 | 担当 |
|---|---|---|
| `director` | 総合制作 | 全体方針、進行、採用判断 |
| `story` | シナリオ | 世界観、脚本、人物、伏線、分岐 |
| `visual` | 映像 | 絵コンテ、ショット、演出、素材 |
| `music` | 音楽 | 作曲、編曲、効果音、映像同期 |
| `game` | ゲーム設計 | 探索、クエスト、状態遷移、Godot |
| `critic` | 独立レビュー | 整合性、品質、実装可能性 |

## 共有と分離

- 会話履歴はワークスペースごとに分離し、別チャットの発言を暗黙に混ぜない。
- 作品の共通設定は会話履歴ではなく、バージョン管理された正本（Canon）から参照する。
- 各チャットは必要な共通資料だけをcontext_refsで受け取る。
- チャット間の引き継ぎは、要約・根拠・提案差分・参照IDを含む明示的なhandoffで行う。
- handoffの受け取りはユーザーが承認するまで、他チャットの指示やツール実行権限にならない。
- サイドチャットは正本を直接編集しない。候補アーティファクトを作り、Critic評価と人間承認を経て反映する。

## 将来のデータ契約

現行の独立サイドチャット保存基盤に、互換性を壊さない形で次の任意属性を追加する。

- `project_id`: 作品・プロジェクトの境界
- `workspace_id`: director/story/visual/music/game/critic
- `context_refs`: 参照する正本・資料のID
- `artifact_refs`: 会話から作られた脚本、音源、映像、コード等
- `parent_handoff_id`: 別チャットからの明示的な引き継ぎ元

メッセージ本文を別チャットに複製する代わりに、handoff artifactを参照する。これにより長い会話の重複やコンテキスト混線を避ける。

## Handoff artifact

`creative-handoff.v1` の最低限の構造：

- handoff_id / project_id / source_workspace_id / target_workspace_id
- objective / summary / decisions
- proposed_changes（正本への候補差分）
- artifact_refs / context_refs
- evidence / critic_status（PASS, HOLD, FAIL）
- requires_user_approval（常にtrue）

## 権限と安全性

1. サイドチャットは会話・設計・候補作成を行う。
2. Goal実行、GitHub書き込み、ローカルMac操作、外部公開は既存の権限ゲートを通す。
3. handoff承認とGoal実行承認は別の承認として扱う。
4. ユーザーごとの所有権を必ず検証し、他ユーザーのプロジェクト・会話・成果物を参照できない。
5. 現行ストアの上限はユーザーあたりアクティブ2件。6領域を同時並行させる将来目標とは差があるため、上限を暗黙に迂回しない。将来の上限変更は、ユーザー単位・プロジェクト単位の公平性、実行コスト、レート制限を含む明示的な移行とテストを必須にする。
6. 失敗時は正本を維持し、候補とレビュー履歴だけを残す。

## 連携フロー

```text
LINE / Web UI
  -> Project STAR-NIGHT
     -> Independent side chats (director/story/visual/music/game/critic)
        -> explicit handoff artifact
           -> critic + continuity checks
              -> user approval
                 -> Goal queue / bounded executor
                    -> versioned candidate artifacts
                       -> approved project canon
```

## 実装段階

- Phase 1: side-chat store（PR #1272）と作品manifestを別々に保つ。
- Phase 2: side-chatにproject_id/workspace_id/context_refsを追加し、所有権テストを維持する。6領域の並行上限は現行2件の制約を踏まえて別途設計する。
- Phase 3: handoff artifactを作成・一覧・承認できるAPI/UIを追加する。
- Phase 4: approved handoffだけをGoal提案へ変換する。Goal承認は別途必須。
- Phase 5: 各ワークスペースから映像・音楽・ゲーム制作JOBを起動し、成果物を同じproject_idで関連付ける。

この文書は将来互換性の設計であり、現時点でMuse型UIや自動エージェント会話が稼働していることを意味しない。

## 映像と音楽の独立制作

- 映像は `visual` ワークスペース、音楽は `music` ワークスペースが担当し、JOB ID・成果物参照・保存先を分離する。
- 映像側は脚本・絵コンテ・ショットリスト・動画候補を、音楽側は音楽設計・MIDI・WAV候補を独立して作る。
- 両方のレビュー済み候補が揃った後、総合制作側が共通タイムラインと明示的な同期マーカーで統合する。
- 同期工程が元の映像・音楽素材を自動上書きしない。修正は各担当チャットへのhandoff候補として返す。
- この分離はデータ契約上の設計。現行クラウドworkerに実ファイル生成機能があるという意味ではなく、Macローカル実行器との接続は別工程。

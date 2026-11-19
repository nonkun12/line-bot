# 星を拾った夜 — Cloud hourly production v1

- 毎時1回、GitHub ActionsのUbuntu runnerだけで候補バンドルを作成する。
- Mac/Bonsai/Hermesは不要。Macは将来の助言・レビュー専用。
- 有料API、外部素材ダウンロード、公開、正史の上書きは行わない。
- 生成物：構造化シナリオ、脚本、絵コンテ、ショットリスト、音楽設計、ゲーム分岐案、構造Critic、オリジナルMIDI/WAV、SHA-256 manifest。
- 各時間のfocus taskは6テーマで順番に変わる。候補はcriticと人間の確認が必要。
- 動画/MP4はまだ生成しない。完成映像やキャラクターアニメーションと誤認させない。
- ArtifactはGitHub Actionsに14日保存。workflow_dispatchで手動実行も可能。

## 起動方法
このworkflowがdefault branchへ取り込まれた後、毎時のscheduleが有効になる。最初はworkflow_dispatchで1回実行し、artifact内のMIDI/WAV・manifestを確認してから定期運転を継続する。

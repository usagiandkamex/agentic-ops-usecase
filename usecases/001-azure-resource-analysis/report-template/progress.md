<!-- このコメントは実行用 progress.md の作成時に削除する。 -->
# Azure リソース分析 実行進捗

- 保存先: `{{REPORT_FOLDER}}`
- 開始日時 (JST): `{{STARTED_AT}}`
- 対象: `{{SCOPE}}`
- 選択した柱: `{{SELECTED_PILLARS}}`

## 実行フェーズ

- [ ] 対象スコープと評価観点の承認を取得
- [ ] Collector 完了、G0 合格
- [ ] 選択した Specialist を同一フェーズで並列起動
- [ ] Reliability: `{{RELIABILITY_STATUS}}`（再試行 `{{RELIABILITY_RETRIES}}` 回）
- [ ] Security: `{{SECURITY_STATUS}}`（再試行 `{{SECURITY_RETRIES}}` 回）
- [ ] Cost Optimization: `{{COST_STATUS}}`（再試行 `{{COST_RETRIES}}` 回）
- [ ] Operational Excellence: `{{OPEX_STATUS}}`（再試行 `{{OPEX_RETRIES}}` 回）
- [ ] Performance Efficiency: `{{PERFORMANCE_STATUS}}`（再試行 `{{PERFORMANCE_RETRIES}}` 回）
- [ ] Fan-in 完了、G2 合格、`.work/` 削除済み
- [ ] Report Writer 完了、G3 合格

## ゲート

- [ ] G0: 共通収集、件数、トポロジ、柱初期状態が整合
- [ ] G1: 選択した各柱の専有 JSON が契約に合格
- [ ] G2: WAF 正規順で決定論的に統合し、一時成果物が残っていない
- [ ] G3: HTML、リンク、数値、テンプレート、安全性がすべて整合

## 反スクリプト宣言

- [ ] `findings.json`、柱別 JSON、HTML を生成・整形する補助スクリプトを作成・実行していない
- [ ] 成果物は `create_file` と編集ツールで直接作成した

## ブロッカー・再試行

`{{BLOCKERS_AND_RETRIES}}`

<!--
実行用ファイル作成時の置換規約:
- 選択柱: status=pending, retries=0, チェックは未完了。
- 未選択柱: status=notSelected, retries=0, チェックは完了。
- G1 合格後: status=completed または downgraded、チェックを完了。
- 再試行時: status=retrying、回数と理由を「ブロッカー・再試行」に追記。
- 最大再試行後: status=failed、後続の fan-in / Writer を停止。
このコメントとすべての {{TOKEN}} は実行用 progress.md に残さない。
-->
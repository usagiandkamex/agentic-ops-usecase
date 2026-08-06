# レポートテンプレート契約

このフォルダは、001 Azure リソース分析の Orchestrator、Collector、WAF Specialist、Report Writer が共有する契約です。

## 実行時の成果物

- `findings.json`: Collector がテンプレートから 1 回だけ作成し、Orchestrator が柱別結果を統合する唯一のデータ源。
- `progress.md`: Orchestrator だけが作成・更新する進捗とゲートの記録。
- `index.html`: Report Writer が `index.html` テンプレートから生成するダッシュボード。
- `<pillar>.html`: Report Writer が `pillar.html` から生成する、選択した柱の詳細ページ。
- `architecture.html`: Report Writer が実リソースと根拠のある配線から生成する構成図。

## 並列実行と所有権

1. Collector は `findings.json` の共通データを確定し、選択した柱を `pending`、未選択柱を `notSelected` にする。
2. Orchestrator は選択した Specialist を同じフェーズで並列起動する。
3. 各 Specialist は `reports/<実行日時>/.work/<pillar>.json` のみを作成する。`findings.json`、`progress.md`、他柱のファイルは変更しない。
4. Orchestrator は全結果を検証後、Reliability、Security、Cost Optimization、Operational Excellence、Performance Efficiency の順で `findings.json` に直列統合する。
5. G2 合格後、Orchestrator は `.work/` を削除する。Report Writer は統合済み `findings.json` だけを読む。

柱別 JSON は `pillar`、`status`、`evidence[]`、`checklist[]`、`passCount`、`evaluatedCount`、`coveragePercent`、`label`、`strengths[]`、`improvements[]`、`limitations[]` を持ちます。`status` は `completed` または `downgraded` のみ G1 合格です。全 RG 分析では各行に `resourceGroup` を持たせ、RG×チェック項目を評価単位にします。

Collector の `resources[].safeProperties` は分析に必要な allowlist 項目だけを保持し、ARM の任意 `properties`、シークレット、トークン、キー、接続文字列、資格情報、アプリ設定値、ユーザーデータを保存しません。`topology.nodes[]` と `edges[]` は RG 名を明示し、RG 間接続も根拠と両端 RG を保持します。

## 生成ルール

- テンプレートは毎回 `read_file` で読み、全トークンと BEGIN/END 区域を置換した完成内容を直接書き出す。
- Python、PowerShell、JavaScript などの生成・整形用補助スクリプトを作成または実行しない。
- `Copy-Item` などでテンプレートを保存先へ複写しない。
- 既存の `<style>`、主要クラス、見出し、テーブル列、リンク構造を維持する。
- `.work/`、別名 findings、一時ファイルを最終成果物に残さない。
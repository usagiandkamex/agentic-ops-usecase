# ユースケース: Azure リソース分析

## 概要

指定した Azure リソースを、**信頼性・セキュリティ・コスト最適化・オペレーショナルエクセレンス・パフォーマンス効率** の WAF 5本柱の観点で分析し、改善に向けた具体的な指摘とアクションを提示する GitHub Copilot ベースのユースケースです。

## 背景 / 課題

- Azure 環境は時間とともにリソースが増え、コストやセキュリティの状態が把握しづらくなる。
- 各観点（信頼性、セキュリティ、コスト最適化、オペレーショナルエクセレンス、パフォーマンス効率）を横断的に確認するには、複数のポータル画面やコマンドを行き来する必要がある。
- 定期的な棚卸し・レビューが属人化しやすい。

## 目的 / 期待効果

- 5観点の分析を GitHub Copilot エージェントで半自動化し、レビューの負荷を下げる。
- 指摘に対して優先度と推奨アクションを付与し、改善のきっかけを提供する。
- Well-Architected Framework の考え方に沿った、再現性のあるレビューを実現する。

## 前提条件

- 対象 Azure サブスクリプションへの **Reader（読み取り）権限**（コスト分析には Cost Management Reader 相当を推奨）。
- 分析基盤として **Azure MCP ツール** が利用できること（推奨）。
  - 本リポジトリには [.vscode/mcp.json](../../.vscode/mcp.json) に **Azure MCP Server の定義を同梱**している。
    VS Code でワークスペースを開くとサーバ起動の確認を求められ（強制ではない）、起動後にツールとして利用できる。
  - 利用前に **`az login`** で Azure に認証する（MCP サーバはローカルの資格情報を自動検出する）。
  - 利用できない場合は **Azure CLI (`az`)** を代替として使用する。
- VS Code + GitHub Copilot 拡張機能。

> 本ユースケースは既定で **読み取り専用（分析）** です。設定変更・削除などの破壊的操作は行いません。

## 利用するエージェント

エージェント/プロンプト/インストラクションの実体は、VS Code が自動検出できるよう
リポジトリ直下の `.github/` 配下に配置しています（本ユースケースは `001-` プレフィックスで識別）。

| 種別 | ファイル | VS Code での呼び出し | 役割 |
| --- | --- | --- | --- |
| エージェント | [.github/agents/001-azure-resource-analyst.agent.md](../../.github/agents/001-azure-resource-analyst.agent.md) | エージェント選択 `azure-resource-analyst` | Azure リソース分析に特化したエージェント |
| インストラクション | [.github/instructions/001-azure-ops.instructions.md](../../.github/instructions/001-azure-ops.instructions.md) | 自動適用 | Azure 分析時の共通ルール（読み取り専用・プレースホルダ化など） |
| プロンプト（信頼性） | [.github/prompts/001-reliability-analysis.prompt.md](../../.github/prompts/001-reliability-analysis.prompt.md) | `/azure-reliability-analysis` | 信頼性・可用性の観点で分析 |
| プロンプト（セキュリティ） | [.github/prompts/001-security-analysis.prompt.md](../../.github/prompts/001-security-analysis.prompt.md) | `/azure-security-analysis` | セキュリティの観点で分析 |
| プロンプト（コスト最適化） | [.github/prompts/001-cost-analysis.prompt.md](../../.github/prompts/001-cost-analysis.prompt.md) | `/azure-cost-analysis` | コスト最適化の観点で分析 |
| プロンプト（オペレーショナルエクセレンス） | [.github/prompts/001-opex-analysis.prompt.md](../../.github/prompts/001-opex-analysis.prompt.md) | `/azure-opex-analysis` | 監視・ガバナンス・運用性の観点で分析 |
| プロンプト（パフォーマンス効率） | [.github/prompts/001-performance-analysis.prompt.md](../../.github/prompts/001-performance-analysis.prompt.md) | `/azure-performance-analysis` | パフォーマンス効率の観点で分析 |

## 手順

1. VS Code の GitHub Copilot Chat で、エージェント **`azure-resource-analyst`** を選択する。
2. 分析対象を指定する。分析は **RG 単位** で、対象範囲は「**単一のリソースグループ**（テナント/サブスクリプション/RG を指定）」または「**サブスクリプション配下の全リソースグループ**（テナント/サブスクリプションを指定）」のいずれか。未指定なら実行時にどちらかを確認される（例: `<TENANT_ID>` / `<SUBSCRIPTION_ID>` / `<RESOURCE_GROUP>`）。
3. **エージェントと「対象リソース」と「評価観点」を同意する（必須）**。エージェントは、対象（分析範囲＝単一 RG か全 RG か・テナント/サブスク/RG）と評価観点（5観点のうち実施分）を提示し、**利用者が同意したものだけ**を、同意後に収集・分析する。観点別プロンプト（例: `/azure-cost-analysis`）を使ってもよい。
4. エージェントが Azure MCP（または `az`）で情報を収集し、観点ごとに指摘・優先度・推奨アクションを提示する。
5. エージェントがレポート（HTML）を生成し、**保存前にレビュー**（プレースホルダ残存・根拠リンク・サマリ整合）してから `reports/` に保存する。
6. 結果をレビューし、必要な改善タスクを起票する。

## 出力例

評価は「達成度」ではなく **ベストプラクティス準拠率（カバレッジ%）＋評価ラベル** で示します（WAF のトレードオフを考慮し、100点型の達成度は用いません）。各観点に **できている点（強み）** と 改善点（トレードオフ付き）を併記します。

HTML レポートは **Azure Portal 風デザイン** で、次のテンプレートを土台に生成されます。

- [report-template/index.html](report-template/index.html): ダッシュボード（総合準拠率のドーナツ＋各ピラーカード→詳細ページへのリンク）
- [report-template/pillar.html](report-template/pillar.html): ピラーごとの詳細（準拠率・強み・改善点・トレードオフ）
- [report-template/architecture.html](report-template/architecture.html): インライン SVG のシステム構成図

下記はピラー詳細の内容イメージ（Markdown 表記）です。

```markdown
## コスト最適化 (Cost Optimization)
- 準拠率: 76%（19/25 項目）🟡 要改善

### できている点（強み）
- 予約割引を一部の VM に適用済み
- 開発環境に自動シャットダウンを設定済み

### 改善点
| 優先度 | 対象 | 指摘 | 推奨アクション | トレードオフ | 根拠（参考） |
| --- | --- | --- | --- | --- | --- |
| 中 | Log Analytics | 日次取り込み上限が未設定 | Daily Cap を設定 | 監視データ欠損のリスク（運用性と相反） | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
| 低 | Managed Disk | 未使用ディスク | 削除またはスナップショット化 | 復旧元データを失う可能性 | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
```

> 生成されたレポートは `reports/azure-resource-analysis_<YYYYMMDD-HHmmss>/`（フォルダ）に保存されます（`index.html`（ダッシュボード）＋ 各ピラー `reliability/security/cost/opex/performance.html`＋ `architecture.html`。同日複数回でも上書きされません）。このフォルダは `.gitignore` 済み（ローカル限定）のため、レポート内ではプレースホルダではなく **実際の ID・リソース名** を記載します（上記のサンプルは公開用のため一般化）。シークレット等の機微情報はローカルでも記載しません。

## 注意事項

- 本ユースケースは **読み取り専用の分析** を前提とし、破壊的操作は行わない。実施する場合はユーザーが内容を確認したうえで別途対応すること。
- **リポジトリにコミットするドキュメント/サンプル**には実 ID・リソース名・個人情報・シークレットを含めず、プレースホルダを使用する（`reports/` のローカルレポートは実値可。ただしシークレットや個人のメール等の PII は記載しない）。
- コスト値やメトリクスは環境・期間により変動するため、あくまで目安として扱う。

## 参考リンク

- [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/)
- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/)

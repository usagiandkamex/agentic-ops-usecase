# ユースケース: Azure リソース分析

## 概要

指定した Azure サブスクリプション / リソースグループ内のリソースを、**費用・セキュリティ・信頼性・パフォーマンス・アラート発生状況** の5観点で分析し、改善に向けた具体的な指摘とアクションを提示する GitHub Copilot ベースのユースケースです。

## 背景 / 課題

- Azure 環境は時間とともにリソースが増え、コストやセキュリティの状態が把握しづらくなる。
- 各観点（コスト最適化、セキュリティ、信頼性、パフォーマンス、監視）を横断的に確認するには、複数のポータル画面やコマンドを行き来する必要がある。
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
| プロンプト（費用） | [.github/prompts/001-cost-analysis.prompt.md](../../.github/prompts/001-cost-analysis.prompt.md) | `/azure-cost-analysis` | コスト最適化の観点で分析 |
| プロンプト（セキュリティ） | [.github/prompts/001-security-analysis.prompt.md](../../.github/prompts/001-security-analysis.prompt.md) | `/azure-security-analysis` | セキュリティの観点で分析 |
| プロンプト（信頼性） | [.github/prompts/001-reliability-analysis.prompt.md](../../.github/prompts/001-reliability-analysis.prompt.md) | `/azure-reliability-analysis` | 信頼性・可用性の観点で分析 |
| プロンプト（パフォーマンス） | [.github/prompts/001-performance-analysis.prompt.md](../../.github/prompts/001-performance-analysis.prompt.md) | `/azure-performance-analysis` | パフォーマンス効率の観点で分析 |
| プロンプト（アラート） | [.github/prompts/001-alert-analysis.prompt.md](../../.github/prompts/001-alert-analysis.prompt.md) | `/azure-alert-analysis` | アラート発生状況・監視構成の観点で分析 |

## 手順

1. VS Code の GitHub Copilot Chat で、エージェント **`azure-resource-analyst`** を選択する。
2. 分析対象を指定する（例: サブスクリプション `<SUBSCRIPTION_ID>`、リソースグループ `<RESOURCE_GROUP>`）。
3. 目的の観点に応じてプロンプトを実行する（例: `/azure-cost-analysis`）。5観点すべてを順に実行してもよい。
4. エージェントが Azure MCP（または `az`）で情報を収集し、観点ごとに指摘・優先度・推奨アクションを提示する。
5. エージェントがレポート（HTML）を生成し、**保存前にレビュー**（プレースホルダ残存・根拠リンク・サマリ整合）してから `reports/` に保存する。
6. 結果をレビューし、必要な改善タスクを起票する。

## 出力例

各観点は、テーブルの上に **サマリ（スコア・優先度比率バー・件数）** を付けて出力します。
複数観点をまとめて実行した場合は、レポート冒頭に総合サマリ（Overview）が付きます。

```markdown
### 費用（Cost） サマリ
- スコア: 68 / 100 🟡 要改善
- 優先度比率: 🟥🟥🟧🟧🟧🟩🟩🟩🟩🟩 （高20% / 中30% / 低50%）
- 指摘件数: 高 2 / 中 3 / 低 5（計 10）

| 優先度 | リソース種別 | 指摘 | 推奨アクション | 根拠（参考） |
| --- | --- | --- | --- | --- |
| 高 | Virtual Machine | 停止中だが割り当て済みで課金が継続している VM が存在 | 不要なら割り当て解除(deallocate)または削除 | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
| 中 | Managed Disk | どの VM にも接続されていない未使用ディスク | 不要なら削除、必要ならスナップショット化 | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
| 低 | Public IP | 未関連付けの Standard Public IP | 不要なら解放 | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |

推定削減額: 概算 XX% / 月（実値は環境により異なります）
```

> 生成されたレポートは `reports/azure-resource-analysis_<YYYYMMDD-HHmmss>.html` に保存されます（同日複数回でも上書きされません）。このディレクトリは `.gitignore` 済み（ローカル限定）のため、レポート内ではプレースホルダではなく **実際の ID・リソース名** を記載します（上記のサンプルは公開用のためプレースホルダ表記）。シークレット等の機微情報はローカルでも記載しません。

## 注意事項

- 本ユースケースは **読み取り専用の分析** を前提とし、破壊的操作は行わない。実施する場合はユーザーが内容を確認したうえで別途対応すること。
- **リポジトリにコミットするドキュメント/サンプル**には実 ID・リソース名・個人情報・シークレットを含めず、プレースホルダを使用する（`reports/` のローカルレポートは実値可。ただしシークレットや個人のメール等の PII は記載しない）。
- コスト値やメトリクスは環境・期間により変動するため、あくまで目安として扱う。

## 参考リンク

- [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/)
- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/)

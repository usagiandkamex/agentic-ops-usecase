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
  - 利用できない場合は **Azure CLI (`az`)** を代替として使用する。
- VS Code + GitHub Copilot 拡張機能。

> 本ユースケースは既定で **読み取り専用（分析）** です。設定変更・削除などの破壊的操作は行いません。

## 利用するエージェント

| 種別 | ファイル | 役割 |
| --- | --- | --- |
| チャットモード | [agents/azure-resource-analyst.chatmode.md](agents/azure-resource-analyst.chatmode.md) | Azure リソース分析に特化した対話モード |
| インストラクション | [instructions/azure-ops.instructions.md](instructions/azure-ops.instructions.md) | Azure 分析時の共通ルール（読み取り専用・プレースホルダ化など） |
| プロンプト（費用） | [prompts/cost-analysis.prompt.md](prompts/cost-analysis.prompt.md) | コスト最適化の観点で分析 |
| プロンプト（セキュリティ） | [prompts/security-analysis.prompt.md](prompts/security-analysis.prompt.md) | セキュリティの観点で分析 |
| プロンプト（信頼性） | [prompts/reliability-analysis.prompt.md](prompts/reliability-analysis.prompt.md) | 信頼性・可用性の観点で分析 |
| プロンプト（パフォーマンス） | [prompts/performance-analysis.prompt.md](prompts/performance-analysis.prompt.md) | パフォーマンス効率の観点で分析 |
| プロンプト（アラート） | [prompts/alert-analysis.prompt.md](prompts/alert-analysis.prompt.md) | アラート発生状況・監視構成の観点で分析 |

## 手順

1. VS Code の GitHub Copilot Chat で、チャットモード **`Azure Resource Analyst`** を選択する。
2. 分析対象を指定する（例: サブスクリプション `<SUBSCRIPTION_ID>`、リソースグループ `<RESOURCE_GROUP>`）。
3. 目的の観点に応じてプロンプトを実行する（例: `/cost-analysis`）。5観点すべてを順に実行してもよい。
4. エージェントが Azure MCP（または `az`）で情報を収集し、観点ごとに指摘・優先度・推奨アクションを提示する。
5. 結果をレビューし、必要な改善タスクを起票する。

## 出力例

```markdown
## 費用分析レポート (サブスクリプション: <SUBSCRIPTION_ID>)

| 優先度 | リソース種別 | 指摘 | 推奨アクション |
| --- | --- | --- | --- |
| 高 | Virtual Machine | 停止中だが割り当て済みで課金が継続している VM が存在 | 不要なら割り当て解除(deallocate)または削除 |
| 中 | Managed Disk | どの VM にも接続されていない未使用ディスク | 不要なら削除、必要ならスナップショット化 |
| 低 | Public IP | 未関連付けの Standard Public IP | 不要なら解放 |

推定削減額: 概算 XX% / 月（実値は環境により異なります）
```

## 注意事項

- 本ユースケースは **読み取り専用の分析** を前提とし、破壊的操作は行わない。実施する場合はユーザーが内容を確認したうえで別途対応すること。
- 出力・ドキュメントに **実 ID・リソース名・個人情報・シークレットを含めない**（プレースホルダを使用）。
- コスト値やメトリクスは環境・期間により変動するため、あくまで目安として扱う。

## 参考リンク

- [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/)
- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/)

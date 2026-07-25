---
name: 'azure-cost-analysis'
description: 'Azure リソースを費用（コスト最適化）の観点で読み取り専用分析する。'
agent: 'azure-resource-analyst'
---

# 費用分析（Cost Analysis）

対象の Azure サブスクリプション / リソースグループを **コスト最適化** の観点で分析してください。
未指定の場合は分析対象（`<SUBSCRIPTION_ID>` / `<RESOURCE_GROUP>`）を最初に確認します。

## 収集する情報（読み取り専用）

- Azure MCP ツールを優先し、利用不可なら Azure CLI (`az`) を代替提示する。
- 主なチェック対象:
  - 停止中でも割り当て済み（deallocate されていない）で課金が続く VM
  - 未接続の Managed Disk / 未関連付けの Public IP など未使用リソース
  - 過剰なサイズ・SKU（オーバープロビジョニング）
  - 低稼働リソース、古い世代の SKU
  - リザーブドインスタンス / Savings Plan / 自動シャットダウンの適用余地

## 出力

分析は **Azure Well-Architected Framework（コスト最適化）** に則って行い、
次の列を持つ表で、優先度順に指摘を示してください。

表の**直前にサマリブロック**を付ける：スコア（0–100 と評価バンド 🟢良好80–100 / 🟡要改唄50–79 / 🔴要対几0–49）、
優先度比率バー（10セルの絵文字 🟥=高 🟧=中 🟩=低）、指摘件数（高/中/低と合計）を表示する。

| 優先度 | リソース種別 | 指摘 | 推奨アクション | 根拠（参考） |
| --- | --- | --- | --- | --- |

「根拠（参考）」には、その指摘の根拠となる **WAF または Microsoft Learn のページ**を記載。
一般的な参照先: <https://learn.microsoft.com/azure/well-architected/cost-optimization/>

最後に、想定される削減効果を **概算（目安）** として述べ、次に着手すべき項目を優先順位付きでまとめてください。
分析結果は `usecases/001-azure-resource-analysis/reports/azure-resource-analysis_<YYYYMMDD-HHmmss>.md` に保存します（同日複数回でも上書きせず、コミットはしない）。

## 注意

- 破壊的操作は行わず、推奨アクションの提示に留める。
- 出力に実 ID・リソース名を含めず、プレースホルダを使用する。
- コスト値は環境・期間で変動するため目安として扱う。

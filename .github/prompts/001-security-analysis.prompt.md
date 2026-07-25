---
name: 'azure-security-analysis'
description: 'Azure リソースをセキュリティの観点で読み取り専用分析する。'
agent: 'azure-resource-analyst'
---

# セキュリティ分析（Security Analysis）

対象の Azure サブスクリプション / リソースグループを **セキュリティ** の観点で分析してください。
未指定の場合は分析対象（`<SUBSCRIPTION_ID>` / `<RESOURCE_GROUP>`）を最初に確認します。

## 収集する情報（読み取り専用）

- Azure MCP ツールを優先し、利用不可なら Azure CLI (`az`) を代替提示する。
- 主なチェック対象:
  - ネットワーク公開状況（NSG の広範な許可、パブリックエンドポイント、SSH/RDP の全開放）
  - ストレージ / DB の公開アクセス、保存時暗号化、TLS 設定
  - ID / アクセス（過剰な権限、未使用の資格情報、マネージド ID 未使用）
  - Key Vault の利用状況、シークレットのハードコード兆候
  - Microsoft Defender for Cloud の推奨事項・セキュアスコア

## 出力

分析は **Azure Well-Architected Framework（セキュリティ）** に則って行い、
次の列を持つ表で、リスクの高い順に指摘を示してください。

表の**直前にサマリブロック**を付ける：スコア（0–100 と評価バンド 🟢良好80–100 / 🟡要改唄50–79 / 🔴要対几0–49）、
優先度比率バー（10セルの絵文字 🟥=高 🟧=中 🟩=低）、指摘件数（高/中/低と合計）を表示する。

| 優先度 | リソース種別 | 指摘（リスク） | 推奨アクション | 根拠（参考） |
| --- | --- | --- | --- | --- |

「根拠（参考）」には、その指摘の根拠となる **WAF または Microsoft Learn のページ**を記載。
一般的な参照先: <https://learn.microsoft.com/azure/well-architected/security/>

最後に、重大リスクの要約と、優先的に対処すべき項目をまとめてください。
分析結果は `usecases/001-azure-resource-analysis/reports/azure-resource-analysis_<YYYYMMDD-HHmmss>.md` に保存します（同日複数回でも上書きせず、コミットはしない）。

## 注意

- 破壊的操作や設定変更は行わず、推奨アクションの提示に留める。
- 発見した機密値（もしあれば）は **出力に転記しない**。存在の指摘に留め、プレースホルダで表現する。
- 実 ID・リソース名・IP を含めず、プレースホルダを使用する。

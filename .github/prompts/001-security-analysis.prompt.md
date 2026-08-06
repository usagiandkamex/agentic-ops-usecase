---
name: 'azure-security-analysis'
description: 'Azure リソースをセキュリティの観点で読み取り専用分析する。'
agent: 'azure-resource-analyst'
---

# セキュリティ分析（Security Analysis）

この prompt は `security` を評価観点の事前選択として `azure-resource-analyst` Orchestrator に渡す。対象と観点の承認後、共通 Collector → `azure-security-specialist` → fan-in → Report Writer の順で委譲する。複数観点が指定された場合、選択された Specialist は同一 fan-out フェーズで並列起動する。

対象の Azure サブスクリプション / リソースグループを **セキュリティ** の観点で分析してください。
分析は RG 単位で行います。対象は「テナント/サブスクリプション/RG（単一RG）」または「テナント/サブスクリプション（配下の全RG）」の2パターンです。未確定の場合は、現在のコンテキストを提示してどちらの対象かを確認し、承認を得てから分析します。

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

表の直前に **準拠率（カバレッジ%）＋評価ラベル**（🟢良好80–100% / 🟡要改善50–79% / 🔴要対応0–49%。達成度ではない）と、改善点の優先度比率・件数を示す。
また **できている点（強み）** を必ず併記する（実構成の根拠に基づき、推測しない）。

| 優先度 | リソース種別 | 指摘（リスク） | 推奨アクション | トレードオフ | 根拠（参考） |
| --- | --- | --- | --- | --- | --- |

「根拠（参考）」には、その指摘に**強く関連する具体的な WAF/Microsoft Learn のガイド**（柱のトップページではなく、チェックリスト項目のガイド等）を記載。
一般的な参照先: <https://learn.microsoft.com/azure/well-architected/security/> （チェックリスト: <https://learn.microsoft.com/azure/well-architected/security/checklist>）

最後に、重大リスクの要約と、優先的に対処すべき項目をまとめてください。
分析結果は `usecases/001-azure-resource-analysis/reports/<YYYYMMDD-HHmmss>/`（フォルダ）に保存します（ダッシュボード `index.html`＋この観点の詳細ページ＋構成図 `architecture.html`）。ローカル限定なので `<...>` は実値に置換。保存前にプレースホルダ残存・根拠リンク・強み/トレードオフ・サマリ整合をレビュー。同日複数回でも上書きせず、コミットはしない。

## 注意

- 破壊的操作や設定変更は行わず、推奨アクションの提示に留める。
- 発見した機密値（シークレット/パスワード/接続文字列等）は、ローカルのレポートでも **転記しない**。存在の指摘に留める。
- レポートは `report-template/*.html` を複製しトークンを置換して作る。**Python / PowerShell 等の生成スクリプト（`.py` / `.ps1` 等）は作らず・実行しない**（`Copy-Item` 等のシェルコピーでも作らない）。
- リポジトリにコミットするドキュメントでは実 ID・リソース名・IP を含めずプレースホルダを使う（ローカル保存のレポートは実値可）。

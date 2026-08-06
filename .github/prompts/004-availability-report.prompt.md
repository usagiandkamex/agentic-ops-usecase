---
name: 'azure-availability-report'
description: 'Azure で構築されたシステムの定期稼働報告（可用性・SLA・稼働率・インシデント・運用点検）を読み取り専用で作成する。'
agent: 'azure-availability-reporter'
---

# 定期稼働報告（Availability Report）

対象の Azure リソースについて、**指定期間（既定は前月の月次）** の **可用性・SLA 達成状況・稼働率・インシデント / アラート・運用点検** を READ 専用で集計し、**定期稼働報告** を作成してください。
集計は RG 単位で行います。対象は「テナント/サブスクリプション/RG（単一RG）」または「テナント/サブスクリプション（配下の全RG）」の 2 パターン、期間は「日次 / 週次 / 月次（既定は前月）/ カスタム」です。**SLA / 稼働率目標は、非機能要求グレードで定義した「構築中システム自身の目標値」を入力ファイル `sla-targets.csv`（未提供なら利用者提示値）から取得します（Azure 公表 SLA で代替しない）**。未確定の場合は、現在のコンテキスト・既定期間・SLA 目標の入力有無を提示して確認し、承認を得てから収集します。

## 収集する情報（読み取り専用）

- Azure MCP ツールを優先し、利用不可なら Azure CLI (`az`) を代替提示する。
- 主な収集対象（照会系のみ・変更やメトリック / スキャンのトリガーはしない）:
  - **対象確定（正典）**: `az resource list -g <RG>` で対象リソースを確定
  - **稼働率 / 可用性**: Resource Health（`healthresources` の availabilityStatuses）・種別別の可用性メトリック（`az monitor metrics list`）から対象期間を集計
  - **インシデント**: アクティビティログ（`az monitor activity-log list`）の Resource Health / Service Health イベント
  - **アラート**: `alertsmanagementresources` の対象期間の発火分・未解決アラート
  - **運用点検**: 診断設定 / メトリックアラートの有無（監視カバレッジ）・バックアップ設定の有無・可用性ゾーン / 冗長構成の有無

## 出力

IPA「非機能要求グレード2018」の **可用性** / **運用・保守性** 項目に紐付けて、次の 4 ページ構成の HTML（Azure Portal 風・自己完結）＋ CSV 2 種 ＋ `findings.json` を生成してください。

- `index.html`: 概要（総合可用性ゲージ・SLA 達成 / 未達・インシデント / 未解決アラート・監視カバレッジ・主なインシデント抜粋）
- `availability.html`: リソース別 稼働率 / SLA 達成状況（SLA 判定）＋ 種別別 SLA サマリ
- `incidents.html`: 期間内インシデント（Resource Health / Service Health）＋ 発火アラート
- `operations.html`: 運用点検チェックリスト（監視カバレッジ / バックアップ設定 / 冗長構成）＋ 非機能要求グレード 項目マッピング

稼働率は情報源の粒度に依存する **目安** と明記し、**SLA 目標はシステム自身の目標値（`sla-targets.csv` 入力・非機能要求グレードで定義）** と突き合わせます（Azure 公表 SLA で代替しない・未入力は「未入力（要指定）」表示で達成判定しない）。是正が必要な項目は **推奨アクション** として提示するに留め、変更は行いません。

成果物は `report-template/*` を `read_file` で読み、`findings.json` の実データで `{{TOKEN}}` と `BEGIN/END` 区域を置換して生成します（HTML/CSV を自作しない・生成スクリプトを作らない）。分析結果は `usecases/004-availability-report/reports/<YYYYMMDD-HHmmss>/`（フォルダ）に保存します。ローカル限定なので `<...>` は実値に置換。保存前にトークン残存・SECTION アンカー・空セクション・サマリ整合・CSV の BOM をレビュー。同日複数回でも上書きせず、コミットはしない。

## 注意

- 全工程 **読み取り専用（READ）**。破壊的操作・アラートの生成 / 変更 / 解決・メトリック / スキャンのトリガーはしない。
- リポジトリにコミットする文書には実 ID / リソース名 / 個人情報 / シークレットを含めない（`reports/` のローカルレポートは実値可・シークレットは不可）。

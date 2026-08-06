# ユースケース: Azure 定期稼働報告

## 概要

Azure で構築されたシステムを対象に、**指定期間（既定は前月の月次）** の **可用性・SLA 達成状況・稼働率・インシデント / アラート**、および **運用監視・バックアップ・冗長構成の点検**を **読み取り専用（READ）** で収集し、**定期稼働報告（HTML マルチページ ＋ CSV ＋ findings.json）** を自動生成する GitHub Copilot ベースのユースケースです。

インプットは IPA「**非機能要求グレード2018**」付録の項目一覧です。そのうち **可用性** と **運用・保守性（通常運用 / 運用監視 / バックアップ）** の、**定期的に人手で実施していた稼働状況の確認・報告**を AI で自動化します。

## 背景 / 課題

- 「非機能要求グレード」で定義される稼働率・SLA・運用監視・バックアップの状態確認は、日次 / 週次 / 月次で人手で実施され、属人化・工数増になりがち。
- Azure では Resource Health・Azure Monitor メトリック・アクティビティログ・アラート・Backup など状態が分散し、期間集計・報告書作成に手間がかかる。
- 定期報告の観点・体裁が担当者ごとにばらつき、再現性が低い。

## 目的 / 期待効果

- 定期稼働報告の収集・集計・レポート化を GitHub Copilot エージェントで半自動化し、工数と属人性を下げる。
- 非機能要求グレードの可用性・運用保守性項目に紐付けた、再現性のある定期報告を実現する。
- SLA 未達・インシデント・監視/バックアップの抜けを可視化し、改善アクションのきっかけを提供する。

## 前提条件

- 対象 Azure サブスクリプションへの **Reader（読み取り）権限**（Resource Health / Azure Monitor / アクティビティログ / アラート / Backup の参照）。
- **システムの SLA / 稼働率目標の入力**（目標値をレポートに出す場合）。この目標は **IPA「非機能要求グレード」で定義した「構築中システム自身の目標値」**であり、Azure サービスの公表 SLA ではない。入力テンプレート [report-template/sla-targets.csv](report-template/sla-targets.csv) に値を埋めて提供する（未提供なら目標列は「未入力（要指定）」表示で達成判定しない）。
- 分析基盤として **Azure MCP ツール** が利用できること（推奨）。利用できない場合は **Azure CLI (`az`)** を代替として使用する。
- 利用前に **`az login`** で Azure に認証する（MCP サーバはローカルの資格情報を自動検出する）。
- VS Code + GitHub Copilot 拡張機能。

> 本ユースケースは既定で **読み取り専用（分析）** です。設定変更・削除・再起動・メトリック / スキャンのトリガーなどは行いません。是正が必要な項目は「推奨アクション」として提示するに留めます。

## 利用するエージェント

エージェント/プロンプト/インストラクションの実体は、VS Code が自動検出できるよう
リポジトリ直下の `.github/` 配下に配置しています（本ユースケースは `004-` プレフィックスで識別）。

| 種別 | ファイル | VS Code での呼び出し | 役割 |
| --- | --- | --- | --- |
| エージェント | [.github/agents/004-azure-availability-reporter.agent.md](../../.github/agents/004-azure-availability-reporter.agent.md) | エージェント選択 `azure-availability-reporter` | 定期稼働報告に特化した読み取り専用エージェント |
| インストラクション | [.github/instructions/004-availability-report.instructions.md](../../.github/instructions/004-availability-report.instructions.md) | 自動適用 | 稼働報告時の共通ルール（読み取り専用・対象期間の同意・プレースホルダ化など） |
| プロンプト | [.github/prompts/004-availability-report.prompt.md](../../.github/prompts/004-availability-report.prompt.md) | `/azure-availability-report` | 定期稼働報告を実行 |

## 手順

まず VS Code の GitHub Copilot Chat で、エージェント **`azure-availability-reporter`** を選択（または `/azure-availability-report` を実行）する。
以降、エージェントは次の **実行プロセス（手順 1 → 7）** を順に進める。**手順 1・2 の同意が得られるまでデータ収集は開始しない**。承認後は、エラー・ブロッカーが無い限り自律的に手順 3〜7 を進める。

| 手順 | 内容 | インプット | アウトプット |
| --- | --- | --- | --- |
| 1. 対象・期間の確認・同意（必須） | 分析範囲（単一 RG かサブスク全 RG か）・対象（テナント/サブスク/RG）・**対象期間（日次/週次/月次/カスタム・既定は前月の月次）** と **SLA/稼働率目標の入力（sla-targets.csv の有無）** を選択肢で確認・同意 | 利用者指示 / `az account show` / sla-targets.csv | 確定した対象・期間・目標入力 |
| 2. 収集能力の判別（必須） | Resource Health / メトリック / アクティビティログ / アラート / Backup の参照可否を判別 | Azure MCP / `az` | 収集能力 |
| （最終確認） | 対象・期間・収集能力を提示して実行承認を得る | 手順 1・2 の合意 | 実行承認 |
| 3. データ収集 | Azure MCP（不可なら `az`）で照会系のみ実行し `findings.json` に記録（対象確定・稼働率・インシデント・アラート） | 承認された対象・期間 | `findings.json`（収集データ） |
| 4. 分析 | 稼働率算出・SLA 目標突合・SLA 判定・運用点検・非機能要求グレード紐付け | `findings.json` | `findings.json`（評価・差し込み値を追記） |
| 5. レポート生成 | テンプレートを読み込み `{{TOKEN}}`／`BEGIN/END` を実データで置換した完成 HTML4 ＋ CSV2 を書き出す | テンプレ ＋ `findings.json` | `index/availability/incidents/operations.html` ＋ 2 CSV |
| 6. 保存前レビュー | トークン残存・テンプレ準拠・SECTION アンカー・空セクション・BOM・機密を自己点検 | 生成した成果物 | 修正済み成果物 ＋ レビュー要約 |
| 7. 保存・提示 | `reports/<YYYYMMDD-HHmmss>/` に保存し要点を提示 | 修正済み成果物 | レポートフォルダ ＋ 要約 |

> **成果物はテンプレート複製で作る**: HTML/CSV は `report-template/*` を読み込み、`findings.json` の実データでトークンを置換して書き出す。
> **Python / PowerShell 等の生成スクリプト（`.py` / `.ps1` 等）は作らず・実行しない**（`Copy-Item` 等のシェルコピーでも作らない）。端末は ① Azure への READ 照会、② 保存フォルダ名の時刻取得（JST）、③ 認証・対象コンテキストの確認/設定、④ CSV の BOM 付与 に限る。

## 出力例

稼働率は「情報源の粒度に依存する **目安**」として示し、**SLA 目標はシステム自身の目標値（入力ファイル `sla-targets.csv`・非機能要求グレードで定義）** と突き合わせます（Azure 公表 SLA では代替しない）。運用点検は監視カバレッジ・バックアップ設定・冗長構成の **設定有無** を点検します。

HTML レポートは **Azure Portal 風デザイン** で、次の 4 ページ構成です。

- `index.html`: 概要（総合可用性ゲージ・SLA 達成 / 未達・インシデント / 未解決アラート・監視カバレッジ・主なインシデント抜粋）
- `availability.html`: リソース別 稼働率 / SLA 達成状況 ＋ 種別別 SLA サマリ
- `incidents.html`: 期間内インシデント（Resource Health / Service Health）＋ 発火アラート
- `operations.html`: 運用点検チェックリスト ＋ 非機能要求グレード 項目マッピング

下記はレポート内容のイメージ（Markdown 表記）です。

```markdown
## 総合サマリ（対象期間: 2026-07 月次）
- 総合可用性: 99.94%（目安）🟢 良好
- SLA 達成 8 / 未達 1 ／ 期間内インシデント 3 ／ 未解決アラート 1 ／ 監視カバレッジ 82%

### リソース別 稼働率（抜粋）
| リソース名 | 種別 | 稼働率(%) | SLA 目標(%) | SLA 判定 | ダウンタイム / 算出方法 |
| --- | --- | --- | --- | --- | --- |
| <RESOURCE_NAME> | virtualMachines | 99.95 | 99.9 | 達成 | 21 分 / Resource Health 集計（目安） |
| <RESOURCE_NAME> | sqlDatabase | 99.80 | 99.99 | 未達 | 86 分 / メトリック集計（目安） |
```

> 生成されたレポートは `reports/<YYYYMMDD-HHmmss>/`（フォルダ）に保存されます（`index/availability/incidents/operations.html` ＋ `availability.csv` / `incidents.csv` ＋ `findings.json`。同日複数回でも上書きされません）。このフォルダは `.gitignore` 済み（ローカル限定）のため、レポート内ではプレースホルダではなく **実際の ID・リソース名** を記載します（上記のサンプルは公開用のため一般化）。シークレット等の機微情報はローカルでも記載しません。

## 注意事項

- 本ユースケースは **読み取り専用の分析** を前提とし、破壊的操作は行わない。是正が必要な項目はユーザーが内容を確認したうえで別途対応すること。
- 稼働率・SLA 達成状況は情報源（Resource Health / メトリック / アクティビティログ）の粒度に依存する **目安** であり、実際の SLA クレジット判定とは異なる場合がある。**SLA 目標はシステム自身の目標値（sla-targets.csv 入力・非機能要求グレードで定義）で、Azure 公表 SLA ではない**（未入力は達成判定しない）。
- **リポジトリにコミットするドキュメント/サンプル**には実 ID・リソース名・個人情報・シークレットを含めず、プレースホルダを使用する（`reports/` のローカルレポートは実値可。ただしシークレットや PII は記載しない）。

## 参考リンク

- [IPA 非機能要求グレード2018（付録 項目一覧 PDF）](https://www.ipa.go.jp/archive/files/000066170.pdf)
- [Azure Well-Architected Framework — 信頼性](https://learn.microsoft.com/azure/well-architected/reliability/)
- [Azure Resource Health](https://learn.microsoft.com/azure/service-health/resource-health-overview)
- [Azure Monitor アラート](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-overview)
- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/)

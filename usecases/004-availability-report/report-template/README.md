# レポートテンプレート（ユースケース 004 定期稼働報告）

**`azure-availability-reporter`（エージェント）** はレポート生成時、このフォルダのテンプレートを **`read_file` で読み込み**、`findings.json` の実データで
`{{TOKEN}}` を置換し `<!-- BEGIN X -->`〜`<!-- END X -->` 区域を実データ件数だけ複製した **完成ファイルを `create_file` で** `reports/<YYYYMMDD-HHmmss>/` に書き出します。
**`Copy-Item` 等のシェルコピーや外部スクリプト実行で作らない**（トークンが未置換のまま残る）。

## 入力ファイル（SLA / 稼働率目標・必須ではないが目標列を出すなら必須）

- **[sla-targets.csv](sla-targets.csv)** — 対象システムの **SLA / 稼働率目標（非機能要求グレードで定義した「構築中システム自身」の目標値）** の入力。**Azure サービスの公表 SLA ではない**。
  - 列: `scope`(system|resourceType|resourceName) / `identifier`(system=\*・resourceType=種別文字列・resourceName=リソース名) / `availabilityTargetPct`(目標稼働率%) / `rtoMinutes`(任意) / `rpoMinutes`(任意) / `note`。`#` 行はコメント。
  - 優先順位: resourceName > resourceType > system。
  - エージェントはこれを `read_file` で読み、`findings.json` の `availability[].slaTarget` / `slaTargetSource` / `rtoTargetMinutes` / `rpoTargetMinutes` の入力元にする。
  - **未入力（該当行なし）のリソースは、目標列を「未入力（要指定）」と表示し達成判定をしない**（Azure 公表 SLA で代替しない）。`findings.json` の `metadata.slaTargetsInput.provided` で入力有無を記録する。
  - このファイルは入力テンプレート。実値を埋めたものはローカル（reports 配下等）で扱い、リポジトリには実値をコミットしない（プレースホルダ使用）。

> **フォルダ名 `<YYYYMMDD-HHmmss>`**: **JST（UTC+9）基準**の実際の実行時刻（秒精度）で命名し、各実行を区別する。
> 取得例（PowerShell）: `[DateTime]::UtcNow.AddHours(9).ToString('yyyyMMdd-HHmmss')`。

## 出力ファイル（3 種類の成果物＋進捗ファイル）

1. **HTML（人が読む・マルチページ・4 ページ）** — `report-template/*.html` を `read_file` で読み、トークン置換と BEGIN/END 行複製で完成させ `create_file` で生成:
   - [index.html](index.html) — 概要（メタ・対象期間・収集能力・総合可用性ゲージ・サマリカード・総評・主なインシデント/アラート抜粋・各ページへのタブリンク）
   - [availability.html](availability.html) — リソース別 稼働率 / SLA 達成状況 ＋ 種別別 SLA サマリ
   - [incidents.html](incidents.html) — 期間内インシデント（Resource Health / Service Health）＋ 発火アラート
   - [operations.html](operations.html) — 運用点検チェックリスト（監視カバレッジ / バックアップ設定 / 冗長構成）＋ 非機能要求グレード 項目マッピング
2. **CSV（機械可読データ）** — ヘッダはそのまま `{{*_ROWS}}` を全データ行に置換して生成（UTF-8 BOM 付き）:
   - [availability.csv](availability.csv) — `resourceName,resourceType,period,availabilityPct,slaTarget,slaTargetSource,rtoTargetMinutes,rpoTargetMinutes,slaMet,downtimeMinutes,method,source,note`（`slaTarget`/`rtoTargetMinutes`/`rpoTargetMinutes` はシステムの目標で `slaTargetSource` はその出所。未入力なら空・`slaMet` は空）
   - [incidents.csv](incidents.csv) — `timestamp,resourceName,resourceType,type,severity,title,durationMinutes,status,source`
3. **[findings.json](findings.json)** — 中間データ（単一のデータ源）。HTML/CSV はこの実データで生成する。
   - `metadata`（period=対象期間 / scope / tenantId / subscription / resourceGroup / collectionMethod / capabilities）
   - `summary`（totalResources / overallAvailabilityPct / slaMetCount / slaBreachedCount / incidentCount / unresolvedAlertCount / monitoringCoveragePct / statusHighlight）
   - `inventory[]`（対象 RG のリソース）/ `availability[]`（リソース別稼働率）/ `incidents[]`（期間内インシデント）/ `alerts[]`（発火アラート）
   - `operationsChecklist[]`（運用点検）/ `slaSummary.byType[]`（種別別 SLA）/ `nfrGradeMapping[]`（非機能要求グレード紐付け）
   - `collectionPlan[]`（capability から導出した収集タスク契約。`task` / `requiredBy` / `dueStep`（3/4） / `status`（`pending`→`done`/`empty-verified`/`downgraded`/`failed`） / `evidence`（`query` / `resultCount` / `collectedAt` / `note`））。各手順の切れ目で `pending` を 0 にしてから次工程へ進むハードゲートに使う。中間データで HTML/CSV には出力しない。
4. **[progress.md](progress.md)** — 実行中の**進捗トラッキング**（ワークフロー遵守の強制）。**起動直後（手順 1 のスコープ確認より前）**に `read_file` で読み `create_file` で作成し（保存先フォルダもここで確定）、各手順の切れ目で `replace_string_in_file` により更新・自己検査してから次工程へ進む。`reports/` 配下のローカル成果物（コミットしない）。

## トークン一覧（各テンプレ先頭コメントが正）

- 共通メタ: `META_DATETIME`(JST) / `PERIOD_LABEL` / `PERIOD_START` / `PERIOD_END` / `META_SCOPE` / `TENANT_ID` / `SUBSCRIPTION_NAME` / `SUBSCRIPTION_ID` / `RESOURCE_GROUP` / `COLLECTION_METHOD`
- 収集能力(index): `CAP_RESOURCE_HEALTH` / `CAP_METRICS` / `CAP_ACTIVITY_LOG` / `CAP_ALERTS` / `CAP_BACKUP`
- 総合(index): `OVERALL_VAL` / `OVERALL_COL`(=var(--good|warn|bad)) / `OVERALL_PILL_CLASS`(good|warn|bad) / `OVERALL_LABEL` / `STATUS_HIGHLIGHT`
- サマリカード(index): `TOTAL_RESOURCES` / `SLA_MET` / `SLA_BREACHED` / `INCIDENT_COUNT` / `UNRESOLVED_ALERTS` / `MONITORING_COVERAGE`
- 区域: `TOP_INCIDENT_ROWS`(index) / `AVAILABILITY_ROWS`・`SLA_TYPE_ROWS`(availability) / `INCIDENT_ROWS`・`ALERT_ROWS`(incidents) / `OPS_CHECKLIST_ROWS`・`NFR_MAPPING_ROWS`(operations)
  - `AVAILABILITY_ROWS` の行トークン: `RESOURCE_NAME` / `RESOURCE_TYPE` / `AVAILABILITY_PCT` / `SLA_TARGET` / `RTO_TARGET` / `RPO_TARGET` / `SLA_MET_LABEL` / `SLA_MET_CLASS`(good|bad|warn) / `DOWNTIME_MIN` / `METHOD_NOTE`（RTO/RPO は目標値の表示のみ・未入力は `—`）

## セクションの並び順

概要（index）→ 稼働率 / 可用性（availability）→ インシデント / アラート（incidents）→ 運用点検（operations）。タブは 4 ページ共通で同順。

## 空セクションの扱い（該当なし / 確認不可・重要）

- **テンプレートのセクション（`<h2>`・テーブル）は 0 件でも削除しない**。`<tbody>` を空のまま残さず、各テンプレ先頭コメントに記載の
  フォールバック行 `<tr><td colspan="<列数>" class="empty">該当なし…</td></tr>` を **1 行だけ**出力してセクションを残す。
- **必須 SECTION アンカー（`<h2>` 削除の機械検知）**: 各 HTML の各 `<h2>` 直前に安定アンカー `<!-- SECTION: x -->` がある。生成時に**削除・改名せず出力に残す**（消してよいのは先頭コメントブロックのみ）。必須アンカー: index=`summary`/`top-incidents`、availability=`availability-method`/`availability-detail`/`sla-summary`、incidents=`incidents-list`/`alerts-list`、operations=`ops-checklist`/`nfr-mapping`。
- **「該当なし」と「確認不可」を区別する**: 収集を実施し実際に 0 件だったときのみ「該当なし」。Resource Health / メトリック / アクティビティログ / アラート / Backup が参照不可で判定・収集できない場合は「確認不可（<capability> 未有効）」と明示する（`capabilities` と矛盾させない）。
- **本ルールは HTML 限定**。CSV は 0 件ならヘッダ行のみ（合成レコードを追加しない）。`findings.json` の配列も空配列のまま。index のサマリカード（件数）は 0 でも数値 `0` を表示する。

## 生成手順（読み込み → 置換 → 検証）

> **ファイル生成の機構（`create_file` の制約対処・重要）**: テンプレは `read_file` の**参照元**で保存先に複製しない。置換・行複製で**完成形にしてから** `create_file` で **1 回だけ**書き出す。既存ファイルの更新は編集ツール `replace_string_in_file` を使う（`create_file` は新規専用・同一パスへ 2 回目の `create_file` はしない）。大量行は骨組み＋`<tbody>` 内の一意センチネル（例 `<!-- ROWS_HERE -->`）→ `replace_string_in_file` で行置換。**生成スクリプト（`.ps1`/`.py` 等）は書かない・実行しない**。

1. `findings.json` テンプレを読み、`{{TOKEN}}` を実値に置換、各配列を実データ数だけ複製して `create_file` で書き出す。
2. 各 HTML テンプレを読み、`{{TOKEN}}` を置換、`<!-- BEGIN X -->`〜`<!-- END X -->` 区域は**内部の 1 行を実データ件数分複製**して書き出す。**0 件でも `<h2>`・テーブルを削除しない／`<tbody>` を空にしない**（フォールバック行を 1 行）。先頭コメントを削除する。
3. 各 CSV テンプレを読み、ヘッダはそのまま `{{*_ROWS}}` を全データ行に置換する（**カンマ/改行/二重引用符を含む値は RFC 4180 で二重引用符囲み**）。
4. CSV を UTF-8 BOM 付きで再保存する（下記「文字コード」）。
5. **検証（必須・全合格まで確定しない）**: 下記「生成後チェック」を端末の READ コマンドで実行し、不合格なら当該ファイルを再生成して再検証する。

出力に `{{...}}` や `<!-- BEGIN/END -->` マーカー、テンプレート先頭コメントを残さないこと。

## 文字コード（CSV の文字化け対策）

- `create_file` は UTF-8 BOM なしで書き出す。Windows 版 Excel は BOM なし UTF-8 を Shift-JIS と誤認し日本語が化ける。
- 対策: CSV は UTF-8 (BOM 付き) で保存する。書き出し後に PowerShell:
  `$raw=Get-Content -Raw -Encoding utf8 $p; Set-Content -Path $p -Value $raw -Encoding utf8BOM -NoNewline`
  先頭 3 バイトが 239,187,191 になれば OK。`findings.json` / HTML / `progress.md` は BOM 不要。

## 生成後チェック（例・端末の READ コマンド）

- 残置トークン 0 件: `Select-String -Path $d\*.html -Pattern '{{|<!-- BEGIN|<!-- END'`（0 件）
- SECTION アンカー残存: 各 HTML に必須アンカーが全て存在（不足 0 件）
- `<footer>` と `class="crumb"` と `<style>` が各 HTML に存在（削除・簡略化していない）
- CSV BOM: 先頭 3 バイトが 239,187,191
- 成果物が HTML4/CSV2/findings.json/progress.md のみ（temp-*/別名 findings-*.json なし）

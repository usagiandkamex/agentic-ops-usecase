# レポートテンプレート（ユースケース 005 Azure リタイア情報レポート）

同梱ツール [`tools/retirement_tool.py`](../tools/README.md) の **`render`** が、このフォルダのテンプレートを読み込み、確定済み `findings.json` の実データで
`{{TOKEN}}` を置換し `<!-- BEGIN X -->`〜`<!-- END X -->` 区域を実データ件数だけ複製した完成ファイルを `reports/<YYYYMMDD-HHmmss>/` に書き出します（レポート生成サブエージェント **`azure-retirement-report-writer`** が実行）。
**エージェントは HTML / CSV / `findings.json` を手で組み立てたり、新しいスクリプトで作ったりしない**（置換は単一パスで、差し込んだデータを再走査しない）。

> **フォルダ名 `<YYYYMMDD-HHmmss>`**: **JST（UTC+9）基準**の実行時刻（秒精度）。`init` が作成し、同日複数回でも上書きしない（既存なら `-2` 等を付ける）。

## ファイル一覧

| テンプレート | 出力 | 作成者 | 説明 |
| --- | --- | --- | --- |
| [findings.json](findings.json) | `findings.json` | ツール（`plan-batches` で骨組み・`merge` で確定・`set-highlight` で総評） | 中核成果物（単一のデータ源）。スキーマ例。`notices[]`（投稿）と `events[]`（リタイアイベント＝一覧の 1 行）を分けて保持する |
| [index.html](index.html) | `index.html` | ツール（`render`） | 単一ページの自己完結 HTML（インライン CSS / JS・外部依存なし）。カテゴリ・製品・影響度・時期・キーワードでフィルタ、列ソート |
| [retirements.csv](retirements.csv) | `retirements.csv` | ツール（`render`） | 1 行 = 1 イベント（UTF-8 BOM 付き・Excel 用） |
| [progress.md](progress.md) | `progress.md` | ツール（全サブコマンド） | 実行中の進捗（`.work/state.json` から毎回生成する。テンプレートは出力例） |
| — | `.work/state.json` / `candidates.json` / `inputs/*.json` / `accepted.json` | ツール | 実行状態・候補・ワーカー入力・受理済み抽出結果（中間データ） |
| — | `.work/batch-<NN>.json` | ワーカー | 並列ワーカーの専有シャード（中間データ）。`finalize` が `.work/` ごと削除する |

最終的なフォルダ内は `index.html` / `retirements.csv` / `findings.json` / `progress.md` の 4 ファイルのみ（`.work/` は削除済み）。

## データモデル（findings.json の要点）

- **`notices[]`**: Azure Updates の投稿（MRC の ID 単位）。`products` / `categories` が空の投稿は、ワーカーが本文から推定し `productSource` / `categorySource` に `inferred` を記録する（推定不可は `Uncategorized`・`categorySource=uncategorized`）。イベントにも同じ `productSource` / `categorySource` を持たせ、HTML では「（推定）」と表示する。
- **`events[]`**: リタイアイベント（HTML / CSV の 1 行）。1 投稿は通常 1 イベント。**本文に「異なる対象 × 異なる最終リタイア日」が明記されている場合のみ**分割し、`eventId=<noticeId>-<n>` とする。再告知・日付更新などで**本文の明記により同一と判断できる投稿は 1 イベントに統合**し（ワーカーの `sameEventAs` が相手の `noticeId` と `eventKey` を指す）、`noticeIds[]` に全投稿 ID を残す（確信度が低いものは統合せず `relatedNoticeIds[]` で関連付けるだけ）。統合は保守的に行う（日付は本文に明記された最新の値、フラグは `true` を優先、マイルストーン・リンクは和集合。詳細は [tools/README.md](../tools/README.md) の「統合規則」）。
- **`retireDate`**: 正確な日付を捏造しない。リタイア日 = **影響が発生する最初の日**（`after D` / `supported until D` は D の翌日、移行期限しか無い場合は期限日＋`ambiguous`）。`precision` = `day`（本文に日付が明記）/ `month`（月のみ判明・`start`=月初・`end`=月末）/ `unknown`。`source` = `description` / `availability` / `none`。本文の日付と availability の月が異なる場合は `dateConflict=true` と `dateNoteJa` に両方を記す。
- **`status` / `daysRemaining`**（JST 暦日・基準日 `asOfDate`）:
  - `daysRemaining` = `retireDate.start` − `asOfDate`（日数・月精度は月初基準で保守的）。`unknown` は `null`。
  - `status` = `retired`（`end` < 基準日）/ `currentMonth`（月精度で `start` ≤ 基準日 ≤ `end`）/ `upcoming`（`start` ≥ 基準日）/ `unknown`。
- **`flags`**: `workloadStop` / `dataLossRisk` / `autoMigration` は **`true` / `false` / `unknown` の 3 値**（文字列）。本文の明記が無ければ `unknown`（`false` にしない）。根拠は `flagEvidence` に原文抜粋（プレーンテキスト・200 文字以内）。
- **`ledger`**: 列挙〜統合の各段階の ID 件数（完全性台帳）。`collectionPlan[]` は手順ゲート用の中間データで HTML / CSV には出さない。

## 影響度の判定ルール（決定論・同梱ツールの `merge` が適用）

影響度 = **重大度 S × 緊急度 U**。ワーカーはフラグと根拠を抽出するだけで、S / U / 影響度は同梱ツールが次の規則で機械的に算出する。

| 区分 | 条件 |
| --- | --- |
| S3 | `workloadStop=true` または `dataLossRisk=true` |
| S1 | `autoMigration=true` かつ `workloadStop`・`dataLossRisk` のいずれも `true` でない |
| S2 | 上記以外（`unknown` を含む・保守的） |
| U3 | `status=retired` / `status=currentMonth` / `daysRemaining ≤ 90` |
| U2 | `daysRemaining ≤ 365` |
| U1 | `daysRemaining > 365` |

| S \ U | U3 | U2 | U1 |
| --- | --- | --- | --- |
| S3 | High | High | Medium |
| S2 | High | Medium | Low |
| S1 | Medium | Low | Low |

- `retireDate.precision=unknown` または `classificationStatus=insufficientEvidence` の場合は **`NeedsReview`（要確認）**（S / U は `null`）。
- `classificationStatus=ambiguous` は算出するが、HTML に「分類に曖昧さあり」と表示する。
- `impactReasonJa` に `S2（停止・消失の明記なし）× U2（残 200 日）→ Medium` の形式で根拠を記録する。

## リンクの許可リスト（ワーカー・HTML の JS 共通）

外部リンクは URL として解析し、次をすべて満たす場合のみ採用する（満たさないリンクは破棄し、HTML ではテキスト表示のみ）。

- スキームが `https`（`http://aka.ms` 等は `https` に置き換えてから判定）で、ユーザー情報（`user:pass@`）を含まない。
- ホストが次のいずれか:
  - `microsoft.com` / `aka.ms` と完全一致、またはドット境界のサブドメイン（例 `learn.microsoft.com`。`evilmicrosoft.com` は不可）
  - 完全一致: `portal.azure.com` / `ms.portal.azure.com` / `ai.azure.com` / `feedback.azure.com` / `azure.github.io`
  - `github.com` は組織が `Azure` / `Azure-Samples` / `microsoft` / `MicrosoftDocs` のパスのみ
- **SafeLinks**（`*.safelinks.protection.outlook.com`）は `url` クエリを復号した実 URL で再判定し、SafeLinks の URL 自体は保存しない（`data` パラメタに送信者情報が含まれうるため）。
- `windows.net` / `azurewebsites.net` / `*.azure.com` の任意サブドメインなど、**利用者が作成できるホストは許可しない**。

## トークン一覧（index.html 先頭コメントが正）

- メタ: `META_DATETIME`(JST) / `AS_OF_DATE` / `SCOPE_LABEL` / `COLLECTION_METHOD` / `CAP_MRC_MCP` / `CAP_RC_API` / `CAP_LEARN_MCP`
- サマリ: `NOTICE_COUNT` / `EVENT_COUNT` / `HIGH_COUNT` / `MEDIUM_COUNT` / `LOW_COUNT` / `NEEDS_REVIEW_COUNT` / `WITHIN_90_COUNT` / `RETIRED_COUNT` / `DATE_CONFLICT_COUNT` / `STATUS_HIGHLIGHT`
- 完全性: `RETIREMENTS_TOTAL` / `INSCOPE_COUNT` / `COMPLEMENT_COUNT` / `ENUM_CONSISTENT` / `CANDIDATE_COUNT` / `PREFILTERED_OUT_COUNT` / `WORKER_RETURNED_COUNT` / `FAILED_COUNT` / `OUT_OF_SCOPE_COUNT` / `MERGED_COUNT`
- データアイランド: `EVENTS_JSON` = `findings.json` の `events` 配列**そのもの**（要素・キーを省略・改名・並べ替えしない。検証ゲート 3c で配列全体を照合する）
- 区域: `CATEGORY_ROWS`（`CATEGORY` / `CAT_TOTAL` / `CAT_HIGH` / `CAT_MEDIUM` / `CAT_LOW` / `CAT_NEEDS_REVIEW`）・`QUARTER_ROWS`（`QUARTER` / `Q_TOTAL` / `Q_HIGH` / `Q_MEDIUM` / `Q_LOW` / `Q_NEEDS_REVIEW`）
- CSV: `RETIREMENT_ROWS`（`events[]` を 1 行ずつ）

## 生成手順（`render` が行う処理の仕様）

`python usecases/005-azure-retirement-report/tools/retirement_tool.py render --run <run>` が次を行う（エージェントは手で組み立てない）。

1. **index.html**: テンプレを読み、先頭コメントを削除し、`{{TOKEN}}` と `BEGIN X`〜`END X` 区域を **1 回の走査で**置換する（差し込んだデータを再走査しないため、データ中のトークン風文字列で壊れない）。
   - **`EVENTS_JSON`**: `findings.json` の `events` 配列を JSON として埋め込み、**文字列中の `<` `>` `&` をそれぞれ `\u003c` `\u003e` `\u0026` にエスケープ**する（閉じ script タグによる脱出防止）。0 件なら `[]`。
   - **HTML テキストのエスケープ**: `STATUS_HIGHLIGHT`・`CATEGORY`・`QUARTER`・`SCOPE_LABEL` 等は `&` `<` `>` `"` `'` を文字実体参照にする。
   - **保持必須**: CSP の `<meta>`・`<style>`・`<span class="crumb">`・`<footer>`・各 `<thead>`・`<!-- SECTION: x -->` アンカー・**本文末尾のロジック用 `<script>`（1 文字も変えない。CSP の sha256 ハッシュで許可しているため、改変すると JavaScript が動かなくなる）**。
2. **retirements.csv**: ヘッダはそのまま、`{{RETIREMENT_ROWS}}` を `events[]` の全要素（1 行 = 1 イベント・`events` と同順）に置換する。
   - 列と値の対応: `retireDateStart` / `retireDateEnd` / `datePrecision` = `retireDate.start` / `.end` / `.precision`、`workloadStop` / `dataLossRisk` / `autoMigration` = `flags.*`、`referenceUrls` = `referenceLinks[].url`、それ以外は `events[]` の同名キー。
   - 配列（`noticeIds` / `relatedNoticeIds` / `categories` / `products` / `referenceUrls`）は ` | ` 区切り、`remediationJa` は各要素を `1) …` `2) …` と番号付けして半角スペース 1 つで連結、`milestones` は `<labelJa>:<date>` を ` | ` 区切り、真偽値（`dateConflict`）は `true` / `false`、`null` と空配列は空欄。
   - **RFC 4180**: カンマ・改行・二重引用符を含む値は二重引用符で囲み、内部の `"` は `""` にする（行区切りは CRLF）。
   - **数式インジェクション対策**: テキスト列の値が `=` `+` `-` `@` またはタブ（`\t`）・CR（`\r`）・LF（`\n`）で始まる場合は先頭に `'` を付ける（数値列 `daysRemaining` / `severityScore` / `urgencyScore` は対象外）。
3. CSV を **UTF-8 BOM 付き**で書く（Excel の文字化け対策）。`findings.json` / HTML / `progress.md` は BOM なし。
4. **検証ゲート**（下記）を実行し、結果を返す。1 つでも不合格なら終了コード 1。

## 空セクションの扱い

- `<h2>`・テーブルは 0 件でも削除しない。`CATEGORY_ROWS` / `QUARTER_ROWS` が 0 件なら、先頭コメント記載のフォールバック行を 1 行だけ出力する。
- 一覧（データアイランド）が 0 件なら `[]` を埋め込む（JS が「該当なし」行を表示する）。CSV は 0 件ならヘッダ行のみ。
- サマリのカードは 0 でも数値 `0` を表示する。

## 検証ゲート（`render` / `verify` / `finalize` が実行・全項目 pass まで確定しない）

再実行は `python usecases/005-azure-retirement-report/tools/retirement_tool.py verify --run <run>`（読み取り専用）。各ゲートの定義:

| ゲート | 合格条件 |
| --- | --- |
| 1 トークン残存 0 | データ領域（データアイランド・CSV のレコード）を除く `index.html` と CSV ヘッダに `{{TOKEN}}`・`<!-- BEGIN` / `<!-- END`・センチネルが無い（データ領域は 3c / 5d で 1 セルずつ照合） |
| 2 SECTION アンカー | `summary` / `retirement-list` / `by-category` / `by-quarter` / `impact-rule` / `sources` の 6 つが残っている |
| 3a〜3c データアイランド | 生の `<` を含まない・JSON として解析できる・`eventId` の並びと配列全体（全キー・全値・キー順）が `findings.json` の `events` と完全一致 |
| 4a / 4b スクリプト・CSP 不変 | 属性なしの `<script>` が出力・テンプレートとも 1 つだけで本体が一致（改行正規化後・コメント込み）、CSP の `<meta>` が一致 |
| 4c CSP ハッシュ | ロジック用 `<script>` 本体の SHA-256（Base64）が CSP の `script-src 'sha256-…'` と一致 |
| 5a〜5d CSV | 先頭 3 バイトが BOM、ヘッダがテンプレートと一致、行数と `eventId` の並びが `events` と一致、全行・全列（列数を含む）が上記の規則で `events` から作る値と完全一致 |
| 6a〜6d サマリ整合 | カードの値・カテゴリ別 / 四半期別の行（並び順を含む。0 件はフォールバック行のみ）・総評が `summary` / `byCategory` / `byQuarter` と一致 |
| 7a 安全性 | `index.html` / `retirements.csv` / `findings.json`（全体）に、パーセント復号・HTML 文字参照の復号の後も含めてメールアドレス・SafeLinks が無く、`index.html` / `retirements.csv` に `<...>` 形式のプレースホルダが無い（結果には種別と JSON パスだけを出し、値は出さない） |
| 7b URL 許可リスト | `findings.json` とデータアイランドの全 `updateUrl` / `referenceLinks[].url` が「リンクの許可リスト」を満たす（空も違反。結果には項目パスと種別だけを出す） |
| 8 成果物 | フォルダ直下が `findings.json` / `index.html` / `progress.md` / `retirements.csv`（＋ `finalize` で削除される `.work/`）のみ |
| G3 | `findings.json` の判定値・`summary`・`byCategory` / `byQuarter`（並び順を含む）・投稿とイベントの双方向対応・`collectionPlan`・台帳（候補 = 返却 ∪ 取得失敗）を再計算して一致 |

- 独立レビュー（`azure-retirement-report-writer`）は、ゲートで照合しない内容の妥当性（総評と件数の整合、要約・日付・対応策・影響度の根拠の矛盾）を確認し、親が `record-review` で記録する。`finalize` はゲート全合格とレビュー合格を前提とする。

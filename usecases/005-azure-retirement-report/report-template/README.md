# レポートテンプレート（ユースケース 005 Azure リタイア情報レポート）

レポート生成サブエージェント **`azure-retirement-report-writer`** は、このフォルダのテンプレートを **`read_file` で読み込み**、確定済み `findings.json` の実データで
`{{TOKEN}}` を置換し `<!-- BEGIN X -->`〜`<!-- END X -->` 区域を実データ件数だけ複製した **完成ファイルを `create_file` で** `reports/<YYYYMMDD-HHmmss>/` に書き出します。
**`Copy-Item` 等のシェルコピーや生成スクリプト（`.py` / `.ps1` / `.js` 等）で作らない**（トークンが未置換のまま残る・規約違反）。

> **フォルダ名 `<YYYYMMDD-HHmmss>`**: **JST（UTC+9）基準**の実行時刻（秒精度）。取得例: `[DateTime]::UtcNow.AddHours(9).ToString('yyyyMMdd-HHmmss')`。同日複数回でも上書きしない。

## ファイル一覧

| テンプレート | 出力 | 作成者 | 説明 |
| --- | --- | --- | --- |
| [findings.json](findings.json) | `findings.json` | オーケストレーター | 中核成果物（単一のデータ源）。スキーマ例。`notices[]`（投稿）と `events[]`（リタイアイベント＝一覧の 1 行）を分けて保持する |
| [index.html](index.html) | `index.html` | report-writer | 単一ページの自己完結 HTML（インライン CSS / JS・外部依存なし）。カテゴリ・製品・影響度・時期・キーワードでフィルタ、列ソート |
| [retirements.csv](retirements.csv) | `retirements.csv` | report-writer | 1 行 = 1 イベント（UTF-8 BOM 付き・Excel 用） |
| [progress.md](progress.md) | `progress.md` | オーケストレーター | 実行中の進捗トラッキング（承認直後に作成し、各手順の切れ目で更新） |
| — | `.work/batch-<NN>.json` | ワーカー | 並列ワーカーの専有シャード（中間データ）。統合後にオーケストレーターが削除する |

最終的なフォルダ内は `index.html` / `retirements.csv` / `findings.json` / `progress.md` の 4 ファイルのみ（`.work/` は削除済み）。

## データモデル（findings.json の要点）

- **`notices[]`**: Azure Updates の投稿（MRC の ID 単位）。`products` / `categories` が空の投稿は、ワーカーが本文から推定し `productSource` / `categorySource` に `inferred` を記録する（推定不可は `Uncategorized`・`categorySource=uncategorized`）。イベントにも同じ `productSource` / `categorySource` を持たせ、HTML では「（推定）」と表示する。
- **`events[]`**: リタイアイベント（HTML / CSV の 1 行）。1 投稿は通常 1 イベント。**本文に「異なる対象 × 異なる最終リタイア日」が明記されている場合のみ**分割し、`eventId=<noticeId>-<n>` とする。再告知・日付更新などで**本文の明記により同一と判断できる投稿は 1 イベントに統合**し（ワーカーの `sameEventAs` が相手の `noticeId` と `eventKey` を指す）、`noticeIds[]` に全投稿 ID を残す（確信度が低いものは統合せず `relatedNoticeIds[]` で関連付けるだけ）。統合は保守的に行う（日付は本文に明記された最新の値、フラグは `true` を優先、マイルストーン・リンクは和集合。詳細はオーケストレーター定義の手順 6）。
- **`retireDate`**: 正確な日付を捏造しない。リタイア日 = **影響が発生する最初の日**（`after D` / `supported until D` は D の翌日、移行期限しか無い場合は期限日＋`ambiguous`）。`precision` = `day`（本文に日付が明記）/ `month`（月のみ判明・`start`=月初・`end`=月末）/ `unknown`。`source` = `description` / `availability` / `none`。本文の日付と availability の月が異なる場合は `dateConflict=true` と `dateNoteJa` に両方を記す。
- **`status` / `daysRemaining`**（JST 暦日・基準日 `asOfDate`）:
  - `daysRemaining` = `retireDate.start` − `asOfDate`（日数・月精度は月初基準で保守的）。`unknown` は `null`。
  - `status` = `retired`（`end` < 基準日）/ `currentMonth`（月精度で `start` ≤ 基準日 ≤ `end`）/ `upcoming`（`start` ≥ 基準日）/ `unknown`。
- **`flags`**: `workloadStop` / `dataLossRisk` / `autoMigration` は **`true` / `false` / `unknown` の 3 値**（文字列）。本文の明記が無ければ `unknown`（`false` にしない）。根拠は `flagEvidence` に原文抜粋（プレーンテキスト・200 文字以内）。
- **`ledger`**: 列挙〜統合の各段階の ID 件数（完全性台帳）。`collectionPlan[]` は手順ゲート用の中間データで HTML / CSV には出さない。

## 影響度の判定ルール（決定論・オーケストレーターが適用）

影響度 = **重大度 S × 緊急度 U**。ワーカーはフラグと根拠を抽出するだけで、S / U / 影響度はオーケストレーターが次の規則で機械的に算出する。

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
- データアイランド: `EVENTS_JSON` = `findings.json` の `events` 配列**そのもの**（要素・キーを省略・改名しない）
- 区域: `CATEGORY_ROWS`（`CATEGORY` / `CAT_TOTAL` / `CAT_HIGH` / `CAT_MEDIUM` / `CAT_LOW` / `CAT_NEEDS_REVIEW`）・`QUARTER_ROWS`（`QUARTER` / `Q_TOTAL` / `Q_HIGH` / `Q_MEDIUM` / `Q_LOW` / `Q_NEEDS_REVIEW`）
- CSV: `RETIREMENT_ROWS`（`events[]` を 1 行ずつ）

## 生成手順（読み込み → 置換 → 検証）

> **ファイル生成の機構**: テンプレは `read_file` の**参照元**で保存先に複製しない。置換・行複製で完成形にしてから `create_file` で **1 回だけ**書き出す。既存ファイルの更新は編集ツールを使う（同一パスへ 2 回目の `create_file` はしない）。大量データは骨組み＋一意センチネルを書き、編集ツールで分割追記する（`findings.json` の events / notices とデータアイランドは最大 20 件ずつ、CSV は最大 40 行ずつ。追記後にセンチネルを必ず削除。中断時は最後に書いた ID の次から再開する）。

1. **index.html**: テンプレを読み、先頭コメントを削除して `{{TOKEN}}` を置換する。
   - **`EVENTS_JSON`**: `findings.json` の `events` 配列を JSON として埋め込み、**文字列中の `<` `>` `&` をそれぞれ `\u003c` `\u003e` `\u0026` にエスケープ**する（閉じ script タグによる脱出防止）。データアイランド内に生の `<` が 1 文字も残らないこと。0 件なら `[]`。
   - **HTML テキストのエスケープ**: `STATUS_HIGHLIGHT`・`CATEGORY`・`QUARTER`・`SCOPE_LABEL` 等は `&` `<` `>` `"` `'` を文字実体参照にする。取得した HTML をそのまま埋め込まない。
   - **保持必須**: CSP の `<meta>`・`<style>`・`<span class="crumb">`・`<footer>`・各 `<thead>`・`<!-- SECTION: x -->` アンカー・**本文末尾のロジック用 `<script>`（1 文字も変えない。CSP の sha256 ハッシュで許可しているため、改変すると JavaScript が動かなくなる）**。
2. **retirements.csv**: ヘッダはそのまま、`{{RETIREMENT_ROWS}}` を `events[]` の全要素（1 行 = 1 イベント・`events` と同順）に置換する。
   - 列と値の対応: `retireDateStart` / `retireDateEnd` / `datePrecision` = `retireDate.start` / `.end` / `.precision`、`workloadStop` / `dataLossRisk` / `autoMigration` = `flags.*`、`referenceUrls` = `referenceLinks[].url`、それ以外は `events[]` の同名キー。
   - 配列（`noticeIds` / `relatedNoticeIds` / `categories` / `products` / `referenceUrls`）は ` | ` 区切り、`remediationJa` は各要素を `1) …` `2) …` と番号付けして半角スペース 1 つで連結、`milestones` は `<labelJa>:<date>` を ` | ` 区切り、真偽値（`dateConflict`）は `true` / `false`、`null` と空配列は空欄。
   - **RFC 4180**: カンマ・改行・二重引用符を含む値は二重引用符で囲み、内部の `"` は `""` にする。
   - **数式インジェクション対策**: テキスト列の値が `=` `+` `-` `@` またはタブ（`\t`）・CR（`\r`）・LF（`\n`）で始まる場合は先頭に `'` を付ける（数値列 `daysRemaining` 等は対象外）。
3. CSV を UTF-8 BOM 付きで再保存する（下記「文字コード」）。
4. **検証ゲート**（下記）を端末の READ コマンドで実行し、不合格なら当該ファイルを修正して再検証する。

## 空セクションの扱い

- `<h2>`・テーブルは 0 件でも削除しない。`CATEGORY_ROWS` / `QUARTER_ROWS` が 0 件なら、先頭コメント記載のフォールバック行を 1 行だけ出力する。
- 一覧（データアイランド）が 0 件なら `[]` を埋め込む（JS が「該当なし」行を表示する）。CSV は 0 件ならヘッダ行のみ。
- サマリのカードは 0 でも数値 `0` を表示する。

## 文字コード（CSV の文字化け対策）

- `create_file` は UTF-8 BOM なしで書き出すため、Excel で文字化けしないよう CSV のみ BOM を付ける:
  `$p="<CSVファイルのパス>"; $raw=Get-Content -Raw -Encoding utf8 $p; Set-Content -Path $p -Value $raw -Encoding utf8BOM -NoNewline`
- 先頭 3 バイトが 239,187,191 になれば OK。`findings.json` / HTML / `progress.md` は BOM 不要。

## 検証ゲート（端末の READ コマンド・全項目 PASS まで確定しない）

`<reportFolder>` を実パスに置き換え、リポジトリのルートで実行する（ファイルを書き換えない読み取り専用の検証）。

```powershell
$d = '<reportFolder>'; $t = 'usecases/005-azure-retirement-report/report-template'
$f = Get-Content -Raw -Encoding utf8 "$d/findings.json" | ConvertFrom-Json
$h = (Get-Content -Raw -Encoding utf8 "$d/index.html") -replace "`r`n","`n"
$tp = (Get-Content -Raw -Encoding utf8 "$t/index.html") -replace "`r`n","`n"
$ids = @($f.events.eventId) -join ','
$r = { param($name, $ok, $info) '{0} {1}{2}' -f ($(if ($ok) { 'PASS' } else { 'FAIL' })), $name, $(if ($info) { " :: $info" } else { '' }) }
# 1) token / marker / sentinel residue = 0
$res = @(Select-String -Path "$d/index.html","$d/retirements.csv" -Pattern '\{\{|<!-- BEGIN|<!-- END|_HERE -->|__ROWS_HERE__|__EVENTS_CHUNK__|__NOTICES_CHUNK__')
& $r '1 no token residue' ($res.Count -eq 0) (($res | Select-Object -First 3) -join ' / ')
# 2) SECTION anchors (6)
$miss = @('summary','retirement-list','by-category','by-quarter','impact-rule','sources' | Where-Object { $h -notmatch "<!-- SECTION: $_ -->" })
& $r '2 section anchors' ($miss.Count -eq 0) ($miss -join ',')
# 3) data island: no raw '<', valid JSON, same eventIds in the same order as findings.events
$island = [regex]::Match($h,'<script type="application/json" id="retirement-data">([\s\S]*?)</script>').Groups[1].Value
& $r '3a island has no raw <' (-not $island.Contains('<'))
$ev = @($island | ConvertFrom-Json)
& $r '3b island eventIds = findings.events' ((@($ev.eventId) -join ',') -eq $ids) "island=$($ev.Count) findings=$(@($f.events).Count)"
# 4) logic script (the only attribute-less <script>; compared as-is incl. comments, since the CSP hash covers them) and CSP meta identical to the template (newlines normalized)
$js = { param($s) $m = [regex]::Matches($s,'<script>([\s\S]*?)</script>'); if ($m.Count -eq 1) { $m[0].Groups[1].Value } else { "<$($m.Count) attribute-less scripts>" } }
$csp = { param($s) [regex]::Match($s,'<meta http-equiv="Content-Security-Policy"[^>]*>').Value }
& $r '4a logic script unchanged' ((& $js $h) -ceq (& $js $tp))
& $r '4b CSP meta unchanged' ((& $csp $h) -ceq (& $csp $tp))
# 5) CSV: BOM, header, row count and eventIds
$bom = [IO.File]::ReadAllBytes("$d/retirements.csv")[0..2] -join ','
& $r '5a csv BOM' ($bom -eq '239,187,191') $bom
$hdrOut = (Get-Content -Encoding utf8 "$d/retirements.csv" -TotalCount 1).TrimStart([char]0xFEFF)
& $r '5b csv header' ($hdrOut -ceq (Get-Content -Encoding utf8 "$t/retirements.csv" -TotalCount 1))
$rows = @(Import-Csv -Encoding utf8 "$d/retirements.csv")
& $r '5c csv rows/eventIds = findings.events' ((@($rows.eventId) -join ',') -eq $ids) "csv=$($rows.Count)"
# 5d) CSV: every record has exactly the header's column count and every cell = value derived from findings.events (rules in step 2 above)
Add-Type -AssemblyName Microsoft.VisualBasic
$cols = (Get-Content -Encoding utf8 "$t/retirements.csv" -TotalCount 1) -split ','
$nl = { param($s) ([string]$s) -replace "`r`n?","`n" }
$jn = { param($a) @($a | Where-Object { $null -ne $_ }) -join ' | ' }
$fmt = { param($k, $v) $s = & $nl $v; if ($k -notin 'daysRemaining','severityScore','urgencyScore' -and $s -match '^[=+\-@\t\n]') { "'" + $s } else { $s } }
$cellsOf = { param($e) $i = 0; [ordered]@{
  eventId = $e.eventId; primaryNoticeId = $e.primaryNoticeId; noticeIds = (& $jn $e.noticeIds); relatedNoticeIds = (& $jn $e.relatedNoticeIds)
  retireDateStart = $e.retireDate.start; retireDateEnd = $e.retireDate.end; datePrecision = $e.retireDate.precision; status = $e.status
  daysRemaining = $e.daysRemaining; impact = $e.impact; severityScore = $e.severityScore; urgencyScore = $e.urgencyScore; impactType = $e.impactType
  workloadStop = $e.flags.workloadStop; dataLossRisk = $e.flags.dataLossRisk; autoMigration = $e.flags.autoMigration; classificationStatus = $e.classificationStatus
  categories = (& $jn $e.categories); categorySource = $e.categorySource; products = (& $jn $e.products); productSource = $e.productSource
  title = $e.title; titleJa = $e.titleJa; affectedScopeJa = $e.affectedScopeJa; summaryJa = $e.summaryJa
  remediationJa = (@($e.remediationJa | Where-Object { $null -ne $_ } | ForEach-Object { $i++; "$i) $_" }) -join ' ')
  remediationStatus = $e.remediationStatus; migrationTarget = $e.migrationTarget
  milestones = (& $jn @($e.milestones | Where-Object { $_ } | ForEach-Object { "$($_.labelJa):$($_.date)" }))
  dateConflict = $(if ($null -eq $e.dateConflict) { '' } elseif ($e.dateConflict -eq $true) { 'true' } else { 'false' })
  dateNoteJa = $e.dateNoteJa; updateUrl = $e.updateUrl; referenceUrls = (& $jn @($e.referenceLinks | Where-Object { $_ } | ForEach-Object { $_.url })) } }
$diff = [Collections.Generic.List[string]]::new(); $recs = [Collections.Generic.List[object]]::new(); $evs = @($f.events | Where-Object { $_ })
if ((@((& $cellsOf ([pscustomobject]@{})).Keys) -join ',') -cne ($cols -join ',')) { $diff.Add('column map != template header') }
$tf = [Microsoft.VisualBasic.FileIO.TextFieldParser]::new([IO.StreamReader]::new((Resolve-Path "$d/retirements.csv").Path, [Text.UTF8Encoding]::new($false), $true))
$tf.SetDelimiters(','); $tf.HasFieldsEnclosedInQuotes = $true; $tf.TrimWhiteSpace = $false
try { [void]$tf.ReadFields(); while (-not $tf.EndOfData) { $recs.Add($tf.ReadFields()) } } catch { $diff.Add("parse: $($_.Exception.Message)") } finally { $tf.Close() }
if ($recs.Count -ne $evs.Count) { $diff.Add("records csv=$($recs.Count) findings=$($evs.Count)") }
for ($n = 0; $n -lt [Math]::Min($recs.Count, $evs.Count); $n++) {
  $row = $recs[$n]; $x = & $cellsOf $evs[$n]
  if ($row.Count -ne $cols.Count) { $diff.Add("$($evs[$n].eventId): columns=$($row.Count)"); continue }
  for ($c = 0; $c -lt $cols.Count; $c++) { if ((& $nl $row[$c]) -cne (& $fmt $cols[$c] $x[$cols[$c]])) { $diff.Add("$($evs[$n].eventId):$($cols[$c])") } } }
& $r '5d csv cells = findings.events' ($diff.Count -eq 0) (($diff | Select-Object -First 5) -join ', ')
# 6) summary cards
$cards = [regex]::Matches($h,'<div class="card[^"]*"><div class="n">([^<]*)</div><div class="l">') | ForEach-Object { $_.Groups[1].Value }
$exp = @($f.summary.eventCount,$f.summary.highCount,$f.summary.mediumCount,$f.summary.lowCount,$f.summary.needsReviewCount,$f.summary.within90DaysCount,$f.summary.retiredCount,$f.summary.dateConflictCount) -join ','
& $r '6a summary cards = findings.summary' (($cards -join ',') -eq $exp) ($cards -join ',')
# 6b/6c) by-category / by-quarter rows = findings.byCategory / byQuarter (same order; 0 rows -> fallback row only)
$rowsOf = { param($from, $to)
  $sec = [regex]::Match($h,"<!-- SECTION: $from -->([\s\S]*?)<!-- SECTION: $to -->").Groups[1].Value
  $body = [regex]::Match($sec,'<tbody>([\s\S]*?)</tbody>').Groups[1].Value
  [regex]::Matches($body,'<tr>([\s\S]*?)</tr>') | ForEach-Object { (@([regex]::Matches($_.Groups[1].Value,'<td[^>]*>([\s\S]*?)</td>') | ForEach-Object { [Net.WebUtility]::HtmlDecode($_.Groups[1].Value) }) -join [char]31) } }
$expRows = { param($items, $key) $x = @($items | Where-Object { $_ } | ForEach-Object { @($_.$key,$_.total,$_.high,$_.medium,$_.low,$_.needsReview) -join [char]31 }); if ($x.Count) { $x } else { @('該当なし（対象期間のリタイア情報はありません）') } }
$catAct = @(& $rowsOf 'by-category' 'by-quarter'); $catExp = @(& $expRows $f.byCategory 'category')
& $r '6b category rows = findings.byCategory' (($catAct -join "`n") -ceq ($catExp -join "`n")) "html=$($catAct.Count) findings=$(@($f.byCategory).Count)"
$qAct = @(& $rowsOf 'by-quarter' 'impact-rule'); $qExp = @(& $expRows $f.byQuarter 'quarter')
& $r '6c quarter rows = findings.byQuarter' (($qAct -join "`n") -ceq ($qExp -join "`n")) "html=$($qAct.Count) findings=$(@($f.byQuarter).Count)"
# 7) safety: no e-mail address / SafeLinks in index.html, retirements.csv or findings.json (whole file, also after percent-decoding and JSON unescaping), no <PLACEHOLDER> in index.html / retirements.csv
$unesc = { param($s) do { $p = $s; $s = [Uri]::UnescapeDataString($s) } while ($s -cne $p); $s }
$texts = [ordered]@{ 'index.html' = $h; 'retirements.csv' = (Get-Content -Raw -Encoding utf8 "$d/retirements.csv")
  'findings.json' = (Get-Content -Raw -Encoding utf8 "$d/findings.json") + "`n" + ($f | ConvertTo-Json -Depth 100) }
$bad = @(foreach ($k in $texts.Keys) { $s = $texts[$k]
  if (($s + "`n" + (& $unesc $s)) -match '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|safelinks\.protection\.outlook\.com') { "${k}: $($Matches[0])" }
  if ($k -ne 'findings.json' -and $s -cmatch '<[A-Z_]{3,}>') { "${k}: $($Matches[0])" } })
& $r '7a no email/safelinks/placeholder' ($bad.Count -eq 0) (($bad | Select-Object -First 3) -join ' / ')
# 7b) every updateUrl / referenceLinks[].url in findings.events and the data island passes the link allowlist (the CSV is covered by 5d)
$okUrl = { param($u) $x = $null
  if (-not [Uri]::TryCreate([string]$u, [UriKind]::Absolute, [ref]$x) -or $x.Scheme -ne 'https' -or $x.UserInfo) { return $false }
  $hn = $x.Host.ToLowerInvariant()
  ($hn -match '(^|\.)(microsoft\.com|aka\.ms)$') -or ($hn -in 'portal.azure.com','ms.portal.azure.com','ai.azure.com','feedback.azure.com','azure.github.io') -or
    ($hn -eq 'github.com' -and $x.AbsolutePath -match '^/(Azure|Azure-Samples|microsoft|MicrosoftDocs)(/|$)') }
$urls = @(@($f.events) + @($ev) | Where-Object { $_ } | ForEach-Object { $_.updateUrl; @($_.referenceLinks | Where-Object { $_ } | ForEach-Object { $_.url }) } | Where-Object { $_ })
$badUrl = @($urls | Where-Object { -not (& $okUrl $_) } | Select-Object -Unique)
& $r '7b all URLs pass the allowlist' ($badUrl.Count -eq 0) (($badUrl | Select-Object -First 3) -join ' / ')
# 8) folder contents (.work/ is removed by the orchestrator afterwards)
$names = @(Get-ChildItem -Force $d | Where-Object Name -ne '.work' | Select-Object -ExpandProperty Name | Sort-Object)
& $r '8 folder contents' (($names -join ',') -eq 'findings.json,index.html,progress.md,retirements.csv') ($names -join ',')
```

- コマンドで検査しない項目は目視で確認する: 総評が `summary.statusHighlight` と一致すること。

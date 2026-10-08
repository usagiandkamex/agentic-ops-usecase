# 同梱ツール `retirement_tool.py`（ユースケース 005）

Azure リタイア情報レポートの**決定論的な処理**（列挙・完全性照合・重複候補のグループ化・バッチ化・シャード検証・再委譲計画・統合・影響度判定・集計・HTML / CSV 描画・検証ゲート・進捗管理）を行う、レビュー済みの CLI です。

- **Python 3.9 以上・標準ライブラリのみ**（`pip install` 不要）。
- エージェントは**このツールのサブコマンドだけ**を実行する。新しいスクリプトやインラインコードを書かない・実行しない（[instructions](../../../.github/instructions/005-retirement-report.instructions.md)）。
- LLM が担うのは判断だけ（収集範囲の承認・本文からの抽出・同一対象の判定・総評・独立レビュー）。

## 使い方

リポジトリのルートで実行する。各サブコマンドは JSON を 1 つ出力し、`next` に次の操作が書かれている。

```text
python usecases/005-azure-retirement-report/tools/retirement_tool.py <サブコマンド> [オプション]
```

| 手順 | サブコマンド | 内容 |
| --- | --- | --- |
| 2 | `probe --scope <type> [--start YYYY-MM --end YYYY-MM] [--as-of YYYY-MM-DD]` | 公開 API の可否・Retirements 総数・範囲の候補件数（ファイルを書かない） |
| 3 | `init --scope <type> [...] --mrc-mcp available\|unavailable` | 保存先フォルダ（JST 秒精度）・`.work/state.json`・`progress.md` を作成 |
| 4 | `enumerate --run <run>` | 列挙・件数照合・事前絞り込み・`.work/same-target-request.json` |
| 4 | `record-same-target --run <run> --pairs "<id>,<id>;..."` / `--none` | LLM が判定した同一対象の組を記録（検証付き） |
| 4 | `plan-batches --run <run>` | 重複候補グループ・バッチ化・`findings.json` 骨組み（G1） |
| 5 | `next-wave --run <run> [--max 6]` | 次に起動するバッチの入力ファイルを作り `dispatch[]` を返す（MRC MCP が `不可` の実行では、各投稿の本文を公開 API から取得して入力ファイルに入れる） |
| 5 | `check-shards --run <run>` | シャードの厳格検証・正規化・再委譲バッチの計画（全バッチ完了で G2） |
| 6 | `merge --run <run>` | 統合・範囲の最終判定・影響度・集計を `findings.json` に書く（G3） |
| 6 | `set-highlight --run <run>` | 編集ツールで書いた `<run>/.work/highlight.txt` の総評を記録（G3 を再実行。記録後にファイルを削除） |
| 7 | `render --run <run>` | `index.html` / `retirements.csv` を生成し検証ゲート 1〜8 を実行（G4） |
| 7 | `record-review --run <run> --result pass\|fail` | 独立レビューの結果を記録（要約は任意で `<run>/.work/review-note.txt` に書く。記録後に削除） |
| 8 | `finalize --run <run>` | G3・G4・レビュー合格を確認し `.work/` を削除（削除に失敗したら `reviewed` のまま終了し、再実行できる） |
| — | `verify --run <run>` | G3 / G4 の読み取り専用の再実行（他のサブコマンドと同じロックを取り、書き込み途中のファイルを照合しない） |
| — | `status [--run <run>]` | 現在地と次の操作（`--run` 省略で最近の実行一覧）。中断からの再開に使う |

- `<type>` = `default` / `futureOnly` / `next12Months` / `all` / `custom`。`--run` は `reports/` 直下のフォルダ名（またはそのパス）。
- 総評・レビュー要約のような**自由記述はコマンドラインに渡さない**（レポート由来の文字列が端末のシェル解析を経ると、引用符やコマンド置換で同梱ツール以外のコマンドが実行され得るため）。オーケストレーターが編集ツールで上記の固定ファイル（UTF-8・16 KB 以下・リンク不可）に書き、サブコマンドがそれを読む。
- 終了コード: `0` 成功 / `1` ゲート不合格 / `2` 使い方・状態のエラー（`error` と `next` を読む）/ `3` ネットワーク・公開 API のエラー（接続失敗のほか、HTTP 200 以外・JSON 以外・サイズ超過・解析できない応答を含む）。

## 状態と再開

- 実行状態は `<run>/.work/state.json` に一元化し、`progress.md` は**毎回 state から生成**する（手で編集しない）。
- 書き込みはすべて一時ファイル → 置換（原子的）。同じ実行への同時実行はロックファイル `reports/.<run>.lock`（`.gitignore` 済み）への OS ファイルロック（POSIX は `flock`、Windows は `msvcrt.locking`）で防ぐ。ロックは保持プロセスの終了時に OS が解放するため、長時間の実行を経過時間だけで古いロックとみなして奪うことはなく、異常終了後に残ったファイルも次の実行を妨げない。
- フェーズ: `initialized` → `enumerated` → `planned` → `collected` → `merged` → `highlighted` → `rendered` → `reviewed` → `finalized`。各サブコマンドは許可されたフェーズでのみ動き、それ以外は `status` に従うよう案内する。
- ワーカー起動中に中断した場合は `check-shards` を実行する（書かれなかったシャードは失敗扱いになり、再委譲が計画される）。
- `render` で G4 が不合格だった場合、`status` は `render` の再実行を案内する（G4 不合格のまま `record-review` は受け付けない）。
- `finalize` は `state.json` 以外の `.work/` の中身を先に削除し、失敗したら state を `reviewed` のまま残してエラーを返す（ファイルを閉じて再実行できる）。続いて `state.json` を削除し（失敗したら `progress.md` も `reviewed` のまま残してエラーを返す）、削除できてから `progress.md` を完了に更新し、最後に `.work/` を削除する。`state.json` が無く `index.html` がある実行は、空の `.work/` が残っていても `status` で完了として扱う。

## 本文の取得（手順 5）

- MRC MCP が `利用可`（`init --mrc-mcp available`）: ワーカーが MRC MCP で本文を取得する（`fetchedVia="MRC MCP"`）。
- MRC MCP が `不可`: ワーカーはネットワークにアクセスしない。`next-wave` が各投稿の本文を公開 API（`GET .../api/v2/azure/<id>`）から取得し、テキストに変換（`<script>` / `<style>` を除去・リンクは許可リストを満たすものだけ `[URL]` で残す・メールアドレス / SafeLinks を伏字化・40,000 文字上限）して入力ファイルの `notices[].body` に入れる（`bodySource="ReleaseCommunicationsApi"`）。`dispatch[].workerAgent` は **`azure-retirement-summarizer-offline`**（`tools: [read, edit]`・Web / MCP / 端末なし）で、オーケストレーターはこのエージェントを起動する。ワーカーはそれだけを本文として抽出し（`fetchedVia="ReleaseCommunicationsApi"`・`learnMcp="notUsed"`）、`body.fetchError` のある投稿は `failedNoticeIds` に入れる（通常の再委譲の対象）。`next-wave` は本文の出所（`bodySource`）・事前取得に失敗した投稿 ID・**入力ファイルの SHA-256** をバッチの state に記録し、`check-shards` はシャードをそれと照合する（下の正規化ルール参照）。
- **API だけを情報源とする境界の担保**（プロンプトの指示に依存しない）:
  - ワーカーのツール構成にネットワーク手段（Web・MRC / Learn MCP・端末）が無い。
  - 入力ファイル（取得済み本文）が起動後に改変されていたら、そのバッチの全投稿を `malformedInput`（再委譲）にする。
  - `source=availability` の既知のリタイア日は、`next-wave` が取得した `body.availabilities` から求めた月（`availabilityMonth` と同じ規則）と一致する `precision=month` の日付だけを残し、それ以外は `unknown` にする（警告を記録）。
  - 既知のリタイア日（`source=description`）・`"true"` / `"false"` のフラグ・`sameEventAs` の根拠（`evidence`）は、取得済み本文（タイトル＋本文）に含まれることを照合する（Unicode 正規化・大文字小文字・記号を無視した部分一致。英数字 8 文字以上）。見つからなければ日付・フラグは `unknown` に、`sameEventAs` は統合候補から外す（警告を記録）。
  - `referenceLinks` は取得済み本文中の `[URL]` に一致するものだけを残す（Learn 補完のリンクは除外し、`supplementedByLearn` は `notFound` に戻す）。`learnMcp` は `notUsed` に固定する。
  - VS Code のエージェント定義ではファイル読み取りのパスを制限できないため、ワーカーが入力ファイル以外を読むことは定義の指示で禁じる。読んだ内容がレポートに入っても、日付・フラグ・統合・リンクは上の照合で取得済み本文に限られ、自由記述（要約・対応策）はサニタイズと独立レビューの対象になる。
- ウェーブ内の全投稿の取得に失敗し、公開 API 自体にも接続できない場合は、状態を変えずに終了コード `3` で終わる（試行回数を消費しない）。ネットワークを確認して `next-wave` を再実行する。

## 収集範囲

`windowStart` / `windowEnd` は JST 暦日・両端含む（`null` は無制限）。事前絞り込みの起点年 `Y` = `windowStart` の 6 か月前の年。

| type | windowStart | windowEnd |
| --- | --- | --- |
| `default` | 基準日の月の 1 日から 3 か月前の月の 1 日 | `null` |
| `futureOnly` | 基準日 | `null` |
| `next12Months` | 基準日 | 基準日の 12 か月後の前日 |
| `all` | `null` | `null` |
| `custom` | 指定開始月の 1 日 | 指定終了月の末日 |

イベントの範囲判定は区間の重なり（`retireDate` の `[start, end]` と `[windowStart, windowEnd]`）。日付不明のイベントは常に範囲内（要確認）。

## 列挙と事前絞り込み（`enumerate`・G1）

- 範囲内候補 = `tags/any(t:t eq 'Retirements') and (availabilities/any(a:a/year ge Y) or not availabilities/any())`、補集合 = `... and availabilities/any() and not availabilities/any(a:a/year ge Y)`。`inScopeCount + complementCount = retirementsTotal`、一意 ID 件数 = `inScopeCount`、列挙前後の総数一致を確認し、不一致なら 1 回再列挙、なお不一致なら `consistent=false` として記録して続行する（レポートの「収集の完全性」に表示）。
- **本文の年による候補補完**: 補集合のタイトル・本文に `Y` 以上の西暦 4 桁（`20xx`）を含む投稿を候補に加える（availability と本文のリタイア日のずれによる取りこぼし防止）。補集合は必ず availability を持ち、ワーカーが根拠にできる日付は本文の西暦・availability の年月だけなので、除外した投稿のリタイア日は最も遅くても `Y` 年 1 月 1 日（< `windowStart`）。
- `ledger.prefilter` の等式（`M` = 補完件数、`C` = 候補件数）:
  - `done`: `screenedCount` = `complementCount`、`excludedCount` = `complementCount` − `M`、`C` = 範囲内候補の一意件数 + `M`
  - `notNeeded`（`all`）: 補集合・補完・除外がすべて 0、`C` = 範囲内候補の一意件数
  - `fallbackAll`（補集合の取得件数が合わない）: `M` = 0・`excludedCount` = 0、補集合の全件（2 回の取得結果の和集合）を候補にする。`screenedCount` = 和集合の一意件数、`C` = 範囲内候補の一意件数 + `screenedCount`。`screenedCount` ≠ `complementCount`（補集合の取りこぼし）なら `consistent=false` として記録する（`consistent=true` のまま不一致なら G1 不合格）

## 重複候補とバッチ（`record-same-target` / `plan-batches`）

- 重複候補グループ = 正規化タイトル（小文字化・先頭の `Retirement:` / `Retirement notice:` / `Action required:` / `Action recommended:` / `Reminder:` / `Update:` を除去・英数字以外を空白）の一致 ＋ LLM が記録した同一対象の組、の連結成分。アンカー = `modified` が最も新しい投稿。グループは**バッチ割当のヒント**で、統合はしない。
- 1 バッチの本文取得は最大 8 件（参照投稿を含む）。8 件以下のグループは同じバッチに入れる。8 件超のグループは、アンカー＋最新 7 件を所有バッチに、残りを 7 件ずつのチャンクにし、チャンクのバッチは所有バッチの確認後に**アンカーを参照投稿として**起動する（アンカーが取得失敗なら、返却済みで最新のメンバーに差し替える）。所有バッチが全件失敗した場合、チャンクのバッチはグループのメンバーが 1 件でも返却されるか、所有バッチのメンバーが全件再試行上限に達するまで起動しない（再委譲バッチと同じウェーブで参照投稿なしに起動して、イベントを `sameEventAs` で結び付けられなくなるのを防ぐ）。
- `record-same-target` は候補外の ID・自己参照・製品が共通しない組を拒否する。`plan-batches` は記録が無いと拒否する（手順の飛ばし防止）。

## シャード検証と再委譲（`check-shards`・G2）

- `fetchedVia` は `"MRC MCP"` / `"ReleaseCommunicationsApi"` の完全一致だけを受け付ける。MRC MCP が `不可` の実行では `"ReleaseCommunicationsApi"` 以外を失敗にする。事前取得で `body.fetchError` になった投稿は、シャードで成功として返されても `fetchFailed` として再委譲する。バッチの state に出所の記録が無い・形式が不正・実行の収集能力と一致しない場合は、そのバッチの全投稿を `malformedInput`（通常の再試行の対象）にする。`dateConflict` は真偽値（または `"true"` / `"false"` 文字列）が必須で、欠落・その他の値はその投稿を失敗にする（`false` とみなさない）。
- マニフェスト（`expectedNoticeIds` = 割当、`returnedNoticeIds ∪ failedNoticeIds` = 割当・重複なし、`notices[].id` = 返却）が崩れたシャードは、割当の全投稿を失敗にする。投稿ごとの列挙値の誤り・必須キーの欠落はその投稿だけ失敗にする。
- 無害な正規化: 月精度の `start` / `end` を月初・月末に、日精度の `end` を `start` に揃える、真偽値を `"true"` / `"false"` 文字列に、対応策が空なら `notFound` に、根拠（`flagEvidence`）が空の `"true"` / `"false"` フラグは `"unknown"` に、出典（`source` が `description` / `availability`）または根拠（`evidence`）が無い既知のリタイア日は `precision="unknown"` に（いずれも警告を記録）。
- サニタイズ: 制御文字の除去・長さ上限、メールアドレス / SafeLinks の伏字化、許可リスト外のリンクの除去（SafeLinks は実 URL に復号して再判定）。
- マニフェストの `learnMcp` は `"available"`（Learn MCP を使用）/ `"fallbackGet"`（Learn MCP が使えず、`learn.microsoft.com` の検索 API への直接 GET で補完）/ `"unavailable"` / `"notUsed"` のいずれかが必須で、欠落・その他の値のシャードは全投稿を失敗にする。`"available"` / `"fallbackGet"` 以外のシャードに Learn 補完のリンク（`source=LearnSearch`）や `remediationStatus=supplementedByLearn` があれば、リンクを除外して `notFound` に戻す（警告を記録。報告上の Learn MCP の可否と矛盾させない）。`"fallbackGet"` のシャードは Learn 補完のリンクだけを残し、`supplementedByLearn` は `notFound` に戻す（直接 GET は検索結果だけでページ本文を読まないため、手順の補完は Learn MCP に限る）。`source=LearnSearch` のリンクは、ホストが `learn.microsoft.com` でなければ除外する。MRC MCP が `不可` の実行（オフラインワーカー）では、`learnMcp` は値によらず `notUsed` とみなす。
- マニフェストの `learnIncomplete`（真偽値または `"true"` / `"false"`）は、補完が必要なイベントのうち Learn MCP で処理できなかったもの（直接 GET へのフォールバック・補完不可）があるかを表す。`learnMcp` はバッチで 1 つの値（Learn MCP 優先）なので、同じバッチ内で Learn MCP とフォールバックが混在したことはこのフラグで表す。`learnMcp="available"` で欠落・不正なら警告付きで `true` とみなす（完全な補完として報告しない）。`fallbackGet` / `unavailable` は常に `true`、`notUsed` とオフライン実行は常に `false` として扱う。
- 収集能力 `capabilities.learnMcp` は、**最終的に受理された投稿を返したバッチ**（再委譲で置き換えられた試行は除く）の `learnMcp` から決める: `available` があれば `利用可`、無く `fallbackGet` があれば `不可（直接取得で補完）`、無く `unavailable` があれば `不可`、いずれも無ければ `未使用`。それらのバッチに `fallbackGet` / `unavailable` が 1 つでもあるか、`learnIncomplete=true` のバッチがあれば、`collectionPlan` の `Remediation:learnSupplement` は `downgraded`（一部の補完が Learn MCP によらず、上限付き・リンクのみ、または補完なし）とする。
- `sameEventAs` は、参照先が実在し（同じシャード内のイベントか、渡した参照投稿のイベント）、**同じ重複候補グループ**に属し、**根拠（`evidence`）が空でない**場合だけ残す。満たさなければ統合候補から外し、警告として記録する（無関係な投稿の誤統合を防ぐ）。参照先が**同じシャード内で検証に失敗した投稿**の場合は、その投稿が再委譲されるため外さずに残し、`merge` で参照先が受理済みのときだけ統合する（再試行上限に達したら統合されない）。
- 失敗した投稿**だけ**を再委譲バッチ `B<NN>-r<n>`（シャード `batch-<NN>-r<n>.json`・既存シャードは上書きしない）にまとめる。試行は**投稿ごとに最大 3 回**。3 回失敗した投稿は `ledger.failedNoticeIds`（`retriesExhausted`）になり、処理は続行する。
- 受理した抽出結果は `.work/accepted.json`（投稿ごとに唯一の有効結果）に保存する。

## 統合規則（`merge`・G3）

- ワーカーの `sameEventAs`（本文の明記による証拠付き）で結ばれたイベントを推移的に 1 つに統合する（バッチをまたぐ参照投稿経由を含む）。証拠の無い重複候補は統合せず `relatedNoticeIds` に入れる。
- 代表 = `modified` が最も新しい投稿（同時刻は ID が大きい方）。`eventId` = 代表の投稿 ID（分割イベントは `<id>-<n>`。それが別の投稿 ID と衝突する場合は `<id>~<n>`）。
- `retireDate` / `dateConflict` / `dateNoteJa`: 本文に明記（`source=description`）のメンバーのうち最も新しい投稿の値。採用しなかった日付は `dateNoteJa` に「旧告知: <日付>」。
- `flags`: いずれかが `"true"` → `"true"`、それ以外でいずれかが `"false"` → `"false"`、すべて `"unknown"` → `"unknown"`。`"true"` と `"false"` が衝突したら `classificationStatus=ambiguous`。
- `classificationStatus`: 代表の値（代表が `insufficientEvidence` で他に判定済みがあればその値）。要約・対応策・移行先・影響種別は代表の値、空なら値を持つ最も新しいメンバーの値。マイルストーン・リンクは和集合。
- 範囲外のイベントは `ledger.outOfScopeAfterExtraction` へ。範囲内イベントを持たない投稿（取得失敗を含む）は `notices[]` から除く。
- 影響度・`summary` / `byCategory`（大文字小文字を区別しない序数比較・`Uncategorized` は末尾）/ `byQuarter`（時系列・`日付不明` は末尾）は [report-template/README.md](../report-template/README.md) のルールで算出する。

## 安全性

- **ネットワーク**: `https://www.microsoft.com/releasecommunications/api/v2/azure`（一覧）と `.../azure/<id>`（MRC MCP が不可の実行での本文）への GET だけ（オリジン固定・リダイレクトを辿らない・タイムアウト・応答サイズ上限・JSON 以外は拒否）。取得データ中の URL には一切アクセスしない。
- **ファイル**: 書き込みは `usecases/005-azure-retirement-report/reports/<run>/` 配下のみ（フォルダ名の形式・リンク / ジャンクションを検査）。`.work/` の削除は `finalize` だけが行う。
- **取得データ**: タイトル・本文・ワーカーの抽出結果はすべて外部データとして扱い、描画は単一パスの置換（差し込んだデータを再走査しない）とシンク別エスケープで行う。
- Azure リソース・サブスクリプションへはアクセスしない。

## 開発・テスト

```text
python -m unittest discover -s usecases/005-azure-retirement-report/tools/tests -v
```

- テストは合成データのみを使い、ネットワークを使わない（公開 API をフェイクに差し替える）。テスト用の実行フォルダは `reports/` 配下に作って終了時に削除する。
- テンプレート（`index.html`）のロジック用 `<script>` を変更したら、CSP の `sha256-…` を更新する（検証ゲート 4c が不一致を検出する）。

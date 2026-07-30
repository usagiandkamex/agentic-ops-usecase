---
name: 'azure-patch-assessment'
description: 'Azure Update Manager の既存評価結果を読み取り専用で参照し、対象 VM のパッチ適用可否・優先度を判定する（適用は行わず提示に留める）。'
agent: 'azure-config-inventory-analyst'
---

# パッチ適用可否判定（Patch Assessment）

棚卸・脆弱性照合を踏まえ、対象 VM の **パッチ適用可否と優先度**を **READ 専用**で判定する。
**適用そのものは行わず**、可否・優先度・推奨手順の提示に留める。
共通ルール・判定基準はエージェント定義 [002-config-inventory-analyst.agent.md](../agents/002-config-inventory-analyst.agent.md) に従う。

## このプロンプトの位置づけ

- **対応手順**: エージェントの **手順 5（パッチ適用可否判定）**（判定基準は〈参照 D〉）。
- **入力**: 対象 VM（手順 3 の棚卸・手順 4 の脆弱性照合の結果）。
- **出力**: `findings.json` の `patchAssessment[]`、および未適用の重要パッチを `vulnerabilities[]` に `findingType=PatchMissing` として追記。
- **READ 専用（適用・評価トリガー禁止）**: Update Manager の結果は **既存の評価結果を Resource Graph（`patchassessmentresources` / `patchinstallationresults`）で READ 参照**する。**新規評価はトリガーしない**。
  禁止: `az vm assess-patches`（評価トリガー）/ `az vm install-patches`（適用）/ Run Command / 拡張機能インストール / 再起動 / 構成変更。

## やること

1. **未適用パッチの把握**: 対象 VM の未適用パッチの有無・件数・分類（Critical / Security / その他）を、既存結果の READ で把握する。**手順 2 で `updateManager` が「利用可」なら `patchassessmentresources` の照会を必ず実行**して `patchAssessment[]` を埋める（省略しない）。**Defender の MDVM と同じ扱い**で、空になるのは **`updateManager=利用可` で実際に対象 VM が無い場合のみ**（`empty-verified`＝該当なし）。**`updateManager=未構成/参照不可` なら「確認不可（Update Manager 未構成）」（`downgraded`）** と明示し、`empty-verified`（該当なし）と混同しない（capabilityDetection と矛盾させない）。
1b. **現行 OS 版数の公開 CVE 横断（Update Manager 非依存・必須）**: 各 VM の現行 OS 版数について、公開ソース（ディストリ/ベンダのセキュリティトラッカー主・NVD/MSRC 補助）で Critical/High の CVE を横断チェックし `vulnerabilities[]`（findingType=CVE）に追加する（Update Manager 未構成でも実施・該当版数が影響を受ける CVE のみ・`CVE:osLookup` タスクを消化）。**OS 版数を製品×版数で一意化し、手順 4 と共通の fetch 台帳（fetchLedger・`pending`/`succeeded`/`failed`）で重複取得を避けつつソース別並列予算（〈参照 M〉。OS/OSパッケージ主体のためディストリ/ベンダのトラッカー 6–8、NVD 補助は無キー=4／APIキー有り=8–10。実効 6–8 並列。429 を受けたソースは予算を一時半減）で fetch（または CVE ルックアップ・ワーカー `azure-cve-lookup-worker` を同予算で並列に）**、HTTP 429 / API 制限は指数バックオフで再試行する。結果は**親 Agent が `(resourceId, findingType, component, currentVersion, identifier)` キーで重複排除して安定順に決定論マージ**し（並列書き込み競合なし）、各バッチの `durationSec`/`resultCount`/`retryCount` 等を記録する（詳細は〈参照 E〉/〈参照 M〉）。
2. **判定区分**:
   - `適用推奨`: 未適用の Critical / Security パッチあり。
   - `適用検討`: その他の更新あり。
   - `情報なし`: 評価未構成・結果なし（EOL / 版数ベースの推奨に留める）。
3. 各判定に**根拠**（未適用パッチ件数・分類、または「情報なし」の理由）を付す。Update Manager 未構成時は「情報なし」とし、手順 4 の EOL / CVE 判定を根拠に更新方針を提示する。

## 出力（`findings.json`）

- `patchAssessment[]`: `resource, missingCritical, missingSecurity, missingOther, judgment, recommendation`（`recommendation` は提示のみの推奨手順）。
- 未適用の重要パッチは `vulnerabilities[]` に `findingType=PatchMissing` / `source=UpdateManager` の項目として追記する。現行 OS 版数の公開 CVE は `findingType=CVE` / `source`=`DistroSecurityTracker`/`NVD`/`MSRC` 等として追記する。
- 最終的に `remediation.html` の「OS パッチ適用可否」節と `vulnerabilities.csv` に反映される（生成は手順 6・出力仕様は〈参照 F〉）。
- **セクション保持（Issue #4）**: `patchAssessment[]` が 0 件でも `remediation.html` の「OS パッチ適用可否」節は削除せず残し、テンプレのフォールバック行で「該当なし」を表示する。Update Manager 未構成・結果なしで判定できない場合は「確認不可（Update Manager 未有効）」と明示する（`findings.json` の配列は空配列のまま）。

## レビュー 5（保存前に必須）

- 各判定に根拠（未適用パッチ件数・分類、または情報なしの理由）を付けたか。
- **整合性チェック**: 手順 2 の `capabilityDetection` と実収集結果が矛盾しないか（Update Manager=利用可なのに `patchAssessment[]` が空になっていないか）。食い違いは `consistencyChecks[]` に記録・解消したか（〈参照 I〉）。
- **切れ目ゲート G3（〈参照 J〉）**: `dueStep=5` のタスク（UpdateManager=利用可なら `UpdateManager:patchassessmentresources`、常時 `CVE:osLookup`）が全て**証跡付きで terminal** か。`pending` が残れば手順 6 へ進まず照会を実行する。証跡なしに `empty-verified` にしていないか。**現行 OS 版数の Critical/High CVE を公開ソースで確認し `vulnerabilities[]` に追加したか（`CVE:osLookup` を消化・製品×版数一意化→ソース別並列予算（〈参照 M〉。実効 6–8 並列・NVD 無キー時は 4）・fetch 台帳で重複取得を防ぎ、親 Agent が決定論マージし、durationSec/retryCount 等の計時を記録したか）。** **消化後に `progress.md` の手順 5・G3 を更新したか（〈参照 K〉）。** **各タスクの `dueStep` 値が正準表どおり（`UpdateManager:patchassessmentresources`/`CVE:osLookup`=5）で、生成後チェックの dueStep 正準検証（NB5）に一致するか。** **`CVE:osLookup` の `evidence` に照合台帳（`expectedCount`/`succeededCount`/`failedCount`）を記録し、収支一致（`expectedCount==succeededCount+failedCount`）・failed 説明責任（`failedCount>0` なら `note` に理由）・`done` なら `expectedCount≥1` を満たすか（生成後チェックの B5・CVE と EOL を同一ロジックで検査）。**
- 適用・評価トリガー等の書き込み操作を一切行っていないか（提示のみか）。
- 未構成時に無い結果を捏造していないか。

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

## 実行（委譲・重要）

**本プロンプトのバインド先はオーケストレーター `azure-config-inventory-analyst`**。このフェーズの実処理（パッチ適用可否判定＝findings.json の patchAssessment 確定）は **collector（`azure-inventory-collector`）へ委譲**して行い、**オーケストレーターは自分で収集・判定を実行しない**（① スコープ解決 → ② 収集能力判別 → ③ 単一承認 → ⑤ collector へ委譲、の順）。collector は質問ツールを持たないため承認後は**無停止・並列で走り切る**。**判定基準（〈参照 D〉）・並列化/fetch 台帳・CVE ソースルーティングの正典は [002-inventory-collector.agent.md](../agents/002-inventory-collector.agent.md)**。**適用そのものは一切行わず提示に留める**（本プロンプトには詳細を重複記載しない）。

## 出力（`findings.json`）

- `patchAssessment[]`: `resource, missingCritical, missingSecurity, missingOther, judgment, recommendation`（`recommendation` は提示のみの推奨手順）。
- 未適用の重要パッチは `vulnerabilities[]` に `findingType=PatchMissing` / `source=UpdateManager` の項目として追記する。現行 OS 版数の公開 CVE は `findingType=CVE` / `source`=`DistroSecurityTracker`/`OSV`/`NVD`/`MSRC` 等として追記する。
- 最終的に `remediation.html` の「OS パッチ適用可否」節と `vulnerabilities.csv` に反映される（生成は手順 6・出力仕様は〈参照 F〉）。
- **セクション保持（Issue #4）**: `patchAssessment[]` が 0 件でも `remediation.html` の「OS パッチ適用可否」節は削除せず残し、テンプレのフォールバック行で「該当なし」を表示する。Update Manager 未構成・結果なしで判定できない場合は「確認不可（Update Manager 未有効）」と明示する（`findings.json` の配列は空配列のまま）。

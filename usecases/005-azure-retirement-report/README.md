# ユースケース: Azure リタイア情報レポート

## 概要

Azure の **リタイア（提供終了・Retirements）情報**を、**特定の Azure リソースを収集せず公開情報のみから**収集し、**リタイア日・影響度・対応策**をまとめた **フィルタ付き単一 HTML ＋ CSV ＋ findings.json** を自動生成する GitHub Copilot ベースのユースケースです。
HTML 上で **カテゴリ（Compute / Databases 等）・製品（リソースの種類）・影響度・リタイア時期・キーワード**で絞り込めます。

## 背景 / 課題

- Azure のリタイア告知は [Azure の更新情報](https://azure.microsoft.com/ja-jp/updates/) に毎月多数掲載され（Retirements タグだけで数百件）、機能更新と混在しているため、定期的な確認・抽出に手間がかかる。
- 告知本文は英語で、リタイア日・影響（停止 / データ消失の有無）・必要な対応が本文中に散在しており、一覧として比較・優先順位付けしにくい。
- 同じリタイアの再告知・日付延長・リマインダーが別投稿として掲載され、重複や最新日付の判断を人手で行っている。

## 目的 / 期待効果

- リタイア情報の収集・要約・優先順位付けを GitHub Copilot エージェントで半自動化し、確認工数と見落としを減らす。
- 影響度を **決定論ルール**（重大度 × 緊急度）で付与し、担当者によらず再現性のある優先順位を得る。
- 自組織の構成を問わない **公開情報ベースの全体像** を作り、各チームが自分のサービス（製品）でフィルタして確認できるようにする（自組織リソースとの突合は [ユースケース 002](../002-config-inventory-vulnerability/README.md) を参照）。

## 前提条件

- **Azure の権限・認証は不要**（Azure リソース・サブスクリプションへはアクセスしない）。
- **Microsoft Release Communications（MRC）MCP サーバ**（推奨・認証不要）。[.vscode/mcp.json](../../.vscode/mcp.json) に `Microsoft Release Communications` として定義済み。ワーカーが本文の取得に使う（利用できない場合は、同梱ツールの `next-wave` が Azure Updates と同一データ源の公開 API `https://www.microsoft.com/releasecommunications/api/v2/azure` から本文を取得してワーカーの入力ファイルに入れる）。
- **Microsoft Learn MCP サーバ**（任意・認証不要）。対応策の補完に使う。[.vscode/mcp.json](../../.vscode/mcp.json) に `Microsoft Learn` として定義済み（無くても動作する）。
- インターネット（`www.microsoft.com` / `learn.microsoft.com`）への HTTPS 接続。列挙・件数照合には公開 API への接続が必須。
- VS Code + GitHub Copilot 拡張機能、**Python 3.9 以降**（同梱ツール [`tools/retirement_tool.py`](tools/README.md) の実行に使用・標準ライブラリのみで追加パッケージ不要）。

> 本ユースケースは **公開情報の READ のみ** です。Azure への照会・変更、外部への書き込みは行いません。

## 利用するエージェント

エージェント / プロンプト / インストラクションの実体は、VS Code が自動検出できるよう `.github/` 配下に `005-` プレフィックスで配置しています。

| 種別 | ファイル | VS Code での呼び出し | 役割 |
| --- | --- | --- | --- |
| エージェント（オーケストレーター） | [.github/agents/005-azure-retirement-analyst.agent.md](../../.github/agents/005-azure-retirement-analyst.agent.md) | エージェント選択 `azure-retirement-analyst` | 収集範囲の確認・承認、同一対象の判定、ワーカーの並列実行、総評、レビュー結果の記録（決定論処理は同梱ツールで実行） |
| サブエージェント（並列ワーカー） | [.github/agents/005-retirement-summarizer.agent.md](../../.github/agents/005-retirement-summarizer.agent.md) | 自動（オーケストレーターから） | 最大 8 件のバッチ単位で本文を取得し、日付・影響フラグ・対応策・リンクを抽出 |
| サブエージェント（レポート生成） | [.github/agents/005-retirement-report-writer.agent.md](../../.github/agents/005-retirement-report-writer.agent.md) | 自動（オーケストレーターから） | 同梱ツールで HTML / CSV を生成・検証し、独立レビューを実施 |
| 同梱ツール | [tools/retirement_tool.py](tools/README.md) | エージェントが実行 | 列挙・完全性照合・バッチ化・シャード検証・統合・影響度判定・集計・描画・検証ゲート・進捗管理（決定論・再開可能） |
| インストラクション | [.github/instructions/005-retirement-report.instructions.md](../../.github/instructions/005-retirement-report.instructions.md) | 自動適用 | 公開情報のみ・同梱ツール以外のスクリプト禁止・判定の原則などの共通ルール |
| プロンプト | [.github/prompts/005-retirement-report.prompt.md](../../.github/prompts/005-retirement-report.prompt.md) | `/azure-retirement-report` | レポート作成を実行 |

## 手順

VS Code の GitHub Copilot Chat で、エージェント **`azure-retirement-analyst`** を選択（または `/azure-retirement-report` を実行）する。
エージェントは次の手順 1 → 8 を進める。**手順 2 の最終承認までファイルを書かず、収集も開始しない**。承認後はエラーが無い限り自律的に完走する（件数が多くても止まらない）。
決定論的な処理は同梱ツール [`tools/retirement_tool.py`](tools/README.md) のサブコマンドで行い、エージェントは判断（範囲の承認・本文の抽出・同一対象の判定・総評・レビュー）だけを担う。中断した場合は `status` で現在地と次の操作を確認して再開できる。

| 手順 | 内容 | 担当（サブコマンド） | アウトプット |
| --- | --- | --- | --- |
| 1. 収集範囲の確認 | 選択肢で確認（既定: 今後予定のすべて＋直近 3 か月にリタイア済み／今後のみ／今後 12 か月／全件／カスタム） | オーケストレーター | 収集範囲・基準日（JST） |
| 2. 収集能力の判別・承認 | MRC MCP / 公開 API の可否と候補件数を確認し、内容を提示して最終承認 | オーケストレーター（`probe`） | 実行承認 |
| 3. 保存先・進捗 | `reports/<YYYYMMDD-HHmmss>/` と `progress.md` を作成 | ツール（`init`） | `progress.md` |
| 4. 列挙・バッチ化 | Retirements タグを全件数・年フィルタ・補集合で照合しながら列挙し、補集合は本文の年で候補を補完（取りこぼし防止）。エージェントが同一対象の組を判定し、重複候補をグループ化してバッチ化 | ツール（`enumerate` / `plan-batches`）＋オーケストレーター（`record-same-target`） | `findings.json`（骨組み） |
| 5. 詳細取得・要約 | バッチごとに並列で本文を取得し、日付・影響フラグ・対応策を抽出。ツールが厳格に検証し、失敗分のみ再委譲 | 並列ワーカー＋ツール（`next-wave` / `check-shards`） | `.work/batch-<NN>.json` |
| 6. 統合・影響度判定 | 同一イベントの統合・範囲の最終判定・決定論ルールで影響度を算出して再計算で検証。総評はエージェントが執筆 | ツール（`merge`）＋オーケストレーター（`set-highlight`） | `findings.json`（確定） |
| 7. レポート生成 | テンプレートから HTML / CSV を生成して検証ゲートを実行し、独立レビュー | レポート生成（`render`）＋オーケストレーター（`record-review`） | `index.html` / `retirements.csv` |
| 8. 完了報告 | ゲートとレビューの合格を確認して `.work/` を削除し、要点を提示 | ツール（`finalize`）＋オーケストレーター | レポートフォルダ＋要約 |

## 影響度の判定ルール

影響度 = **重大度 S × 緊急度 U**。ワーカーは本文の明記からフラグ（`true` / `false` / `unknown`）と根拠を抽出し、同梱ツールが機械的に算出します。

- **S3（重大）**: リタイア後に停止・利用不可、またはデータ / リソースの削除・消失が明記されている
- **S1（軽微）**: Microsoft による自動移行が明記され、停止・消失の明記が無い
- **S2（中）**: 上記以外（不明を含む・保守的）
- **U3**: リタイア済み・当月・残り 90 日以内 ／ **U2**: 残り 365 日以内 ／ **U1**: 365 日超

| S \ U | U3 | U2 | U1 |
| --- | --- | --- | --- |
| S3 | High | High | Medium |
| S2 | High | Medium | Low |
| S1 | Medium | Low | Low |

リタイア日が特定できない、または判定の根拠が不足する場合は **要確認** とします。詳細は [report-template/README.md](report-template/README.md) を参照してください。

## 出力例

`index.html` は Azure Portal 風の単一ページで、サマリ（影響度別件数・90 日以内・リタイア済み）、フィルタ付き一覧、カテゴリ別 / 四半期別件数、影響度の判定ルール、収集の完全性で構成されます。一覧のイメージ（Markdown 表記・値は例示）:

```markdown
| リタイア日 | 残日数 | 影響度 | カテゴリ / 製品 | 内容 | 影響種別 | 対応策 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-12-31 | 91 日 | High（S3×U2） | Compute / Virtual Machines | <SKU> シリーズ VM のリタイア（停止・割り当て解除） | SKU・シリーズ廃止 [停止] | 移行先: <SKU>（後継シリーズへサイズ変更） |
| 2027-03（月のみ） | 約 151 日 | Medium（S2×U2） | Web / App Service | <機能> の廃止 | 機能廃止 [停止 不明] | 公式な必須対応を特定できず・要確認 |
| 2027-09-30 | 364 日 | Low（S1×U2） | Databases / <PRODUCT> | <版> の自動アップグレード | 版・API・ランタイム廃止 [自動移行] | 移行後の動作確認 |
```

> 生成されたレポートは `reports/<YYYYMMDD-HHmmss>/`（`index.html` / `retirements.csv` / `findings.json` / `progress.md`）に保存されます。このフォルダは `.gitignore` 済み（ローカル限定）です。

## 注意事項

- 本レポートは基準日時点の **公開情報の要約** です。リタイア日・対応策は Microsoft により変更されることがあり、要約・翻訳には誤りが含まれうるため、最終判断は必ず各行のリンク先の原文を確認してください。
- 影響度は **一般的な目安** で、自組織での利用有無・影響度は別途確認が必要です（自組織リソースとの突合はユースケース 002 を参照）。
- 本文中のリンクは Microsoft 公式ドメインの許可リストを満たすものだけを掲載し、Outlook SafeLinks は実 URL に展開します。メールアドレス・個人名は出力しません。
- **リポジトリにコミットするドキュメント / サンプル**には実データを含めず、例示値を使用してください（`reports/` のローカルレポートはコミットしない）。

## 参考リンク

- [Azure の更新情報（Azure Updates）](https://azure.microsoft.com/ja-jp/updates/)
- [Microsoft リリース コミュニケーション MCP サーバーの使用を開始する](https://learn.microsoft.com/ja-jp/microsoft-365/admin/manage/mrc-mcp)
- [Microsoft Learn MCP Server](https://learn.microsoft.com/training/support/mcp)
- [Azure Advisor のサービス リタイア ブック](https://learn.microsoft.com/azure/advisor/advisor-workbook-service-retirement)

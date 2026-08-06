# ユースケース: Azure リソース分析

## 概要

指定した Azure リソースを、**信頼性・セキュリティ・コスト最適化・オペレーショナルエクセレンス・パフォーマンス効率** の WAF 5本柱の観点で分析し、改善に向けた具体的な指摘とアクションを提示する GitHub Copilot ベースのユースケースです。

## 背景 / 課題

- Azure 環境は時間とともにリソースが増え、コストやセキュリティの状態が把握しづらくなる。
- 各観点（信頼性、セキュリティ、コスト最適化、オペレーショナルエクセレンス、パフォーマンス効率）を横断的に確認するには、複数のポータル画面やコマンドを行き来する必要がある。
- 定期的な棚卸し・レビューが属人化しやすい。

## 目的 / 期待効果

- 5観点の分析を GitHub Copilot エージェントで半自動化し、レビューの負荷を下げる。
- 指摘に対して優先度と推奨アクションを付与し、改善のきっかけを提供する。
- Well-Architected Framework の考え方に沿った、再現性のあるレビューを実現する。

## 前提条件

- 対象 Azure サブスクリプションへの **Reader（読み取り）権限**（コスト分析には Cost Management Reader 相当を推奨）。
- 分析基盤として **Azure MCP ツール** が利用できること（推奨）。
  - 本リポジトリには [.vscode/mcp.json](../../.vscode/mcp.json) に **Azure MCP Server の定義を同梱**している。
    VS Code でワークスペースを開くとサーバ起動の確認を求められ（強制ではない）、起動後にツールとして利用できる。
  - 利用前に **`az login`** で Azure に認証する（MCP サーバはローカルの資格情報を自動検出する）。
  - 利用できない場合は **Azure CLI (`az`)** を代替として使用する。
- VS Code + GitHub Copilot 拡張機能。

> 本ユースケースは既定で **読み取り専用（分析）** です。設定変更・削除などの破壊的操作は行いません。

## 利用するエージェント

エージェント/プロンプト/インストラクションの実体は、VS Code が自動検出できるよう
リポジトリ直下の `.github/` 配下に配置しています（本ユースケースは `001-` プレフィックスで識別）。

| 種別 | ファイル | VS Code での呼び出し | 役割 |
| --- | --- | --- | --- |
| Orchestrator | [.github/agents/001-azure-resource-analyst.agent.md](../../.github/agents/001-azure-resource-analyst.agent.md) | エージェント選択 `azure-resource-analyst` | 対象・観点の承認、並列委譲、ゲート、統合、完了報告 |
| Collector | [.github/agents/001-resource-collector.agent.md](../../.github/agents/001-resource-collector.agent.md) | 直接呼び出し不可 | 共通リソースと実トポロジの READ 収集、`findings.json` 初期化 |
| Specialist（信頼性） | [.github/agents/001-reliability-specialist.agent.md](../../.github/agents/001-reliability-specialist.agent.md) | 直接呼び出し不可 | Reliability の評価と専有中間 JSON |
| Specialist（セキュリティ） | [.github/agents/001-security-specialist.agent.md](../../.github/agents/001-security-specialist.agent.md) | 直接呼び出し不可 | Security の評価と専有中間 JSON |
| Specialist（コスト） | [.github/agents/001-cost-specialist.agent.md](../../.github/agents/001-cost-specialist.agent.md) | 直接呼び出し不可 | Cost Optimization の評価と専有中間 JSON |
| Specialist（運用性） | [.github/agents/001-opex-specialist.agent.md](../../.github/agents/001-opex-specialist.agent.md) | 直接呼び出し不可 | Operational Excellence の評価と専有中間 JSON |
| Specialist（性能） | [.github/agents/001-performance-specialist.agent.md](../../.github/agents/001-performance-specialist.agent.md) | 直接呼び出し不可 | Performance Efficiency の評価と専有中間 JSON |
| Report Writer | [.github/agents/001-report-writer.agent.md](../../.github/agents/001-report-writer.agent.md) | 直接呼び出し不可 | 統合済み findings から HTML を生成・独立レビュー |
| インストラクション | [.github/instructions/001-azure-ops.instructions.md](../../.github/instructions/001-azure-ops.instructions.md) | 自動適用 | Azure 分析時の共通ルール（読み取り専用・プレースホルダ化など） |
| プロンプト（信頼性） | [.github/prompts/001-reliability-analysis.prompt.md](../../.github/prompts/001-reliability-analysis.prompt.md) | `/azure-reliability-analysis` | 信頼性・可用性の観点で分析 |
| プロンプト（セキュリティ） | [.github/prompts/001-security-analysis.prompt.md](../../.github/prompts/001-security-analysis.prompt.md) | `/azure-security-analysis` | セキュリティの観点で分析 |
| プロンプト（コスト最適化） | [.github/prompts/001-cost-analysis.prompt.md](../../.github/prompts/001-cost-analysis.prompt.md) | `/azure-cost-analysis` | コスト最適化の観点で分析 |
| プロンプト（オペレーショナルエクセレンス） | [.github/prompts/001-opex-analysis.prompt.md](../../.github/prompts/001-opex-analysis.prompt.md) | `/azure-opex-analysis` | 監視・ガバナンス・運用性の観点で分析 |
| プロンプト（パフォーマンス効率） | [.github/prompts/001-performance-analysis.prompt.md](../../.github/prompts/001-performance-analysis.prompt.md) | `/azure-performance-analysis` | パフォーマンス効率の観点で分析 |

## 手順

まず VS Code の GitHub Copilot Chat で、Orchestrator **`azure-resource-analyst`** を選択する（単一観点だけなら観点別プロンプト `/azure-cost-analysis` 等を使ってもよい）。
以降、Orchestrator は次の **実行プロセス（手順 1 → 7）** を進める。**手順 1・2 の同意が得られるまでデータ収集・分析は開始しない**。承認後は、エラー・ブロッカーが無い限り追加質問せず手順 3〜7 を完走する。

| 手順 | 内容 | インプット | アウトプット |
| --- | --- | --- | --- |
| 1. 対象リソースの確認・同意（必須） | 分析範囲（単一 RG か、サブスク配下の全 RG か）と対象（テナント/サブスク/RG）を選択肢で確認・同意 | 利用者指示 / `az account show` / `az group list` | 確定した対象 |
| 2. 評価観点の確認・同意（必須） | 5 観点のうち実施分を選択肢（複数選択可）で確認・同意 | 利用者指示 | 実施する観点 |
| （最終確認） | 対象範囲・対象・観点を提示して実行承認を得る | 手順 1・2 の合意 | 実行承認 |
| 3. 共通収集 | Collector が Azure MCP（不可なら `az`）でリソースとトポロジを READ 収集 | 承認された対象・観点 | 初期 `findings.json` |
| 4. 柱別並列分析 | 選択した Specialist を同一 fan-out で並列起動し、各柱が専有 `.work/<pillar>.json` を作成 | 共通 `findings.json` | 柱別評価、G1 結果 |
| 5. 決定論的統合 | Orchestrator が WAF 正規順で柱結果を直列統合し、summary を確定して `.work/` を削除 | 全柱の G1 合格結果 | 完成 `findings.json`、G2 結果 |
| 6. レポート生成・レビュー | Report Writer がテンプレートから HTML を生成し、リンク・数値・構成図・機密を独立レビュー | テンプレート＋完成 `findings.json` | `index.html`＋選択柱＋`architecture.html`、G3 結果 |
| 7. 保存・提示 | Orchestrator が `progress.md` を完了し、生成物と要点を提示 | G0〜G3 合格結果 | レポートフォルダ＋要約 |

> **柱は並列、共有ファイルは直列**: Specialist は最終 `findings.json` や `progress.md` を変更せず、それぞれの専有中間 JSON だけを書き込みます。失敗した柱だけ最大 2 回再試行し、全柱の統合後に中間 `.work/` を削除します。

> **成果物はテンプレート複製で作る**: HTML は `report-template/*.html` を読み込み、`findings.json` の実データでトークンを置換して書き出す。
> **Python / PowerShell 等の生成スクリプト（`.py` / `.ps1` 等）は作らず・実行しない**（`Copy-Item` 等のシェルコピーでも作らない）。端末は ① Azure への READ 照会、② 保存フォルダ名の時刻取得（JST）、③ 認証・対象コンテキストの確認/設定（`az login` / `az account set` 等）、④ 生成済み JSON / HTML / ファイル構成の読み取り専用検証 の 4 用途にのみ使う。

最後に、生成されたレポートを確認し、必要な改善タスクを起票する。

## 出力例

評価は「達成度」ではなく **ベストプラクティス準拠率（カバレッジ%）＋評価ラベル** で示します（WAF のトレードオフを考慮し、100点型の達成度は用いません）。各観点に **できている点（強み）** と 改善点（トレードオフ付き）を併記します。

HTML レポートは **Azure Portal 風デザイン** で、次のテンプレートを土台に生成されます。

- [report-template/index.html](report-template/index.html): ダッシュボード（総合準拠率のドーナツ＋各ピラーカード→詳細ページへのリンク）
- [report-template/pillar.html](report-template/pillar.html): ピラーごとの詳細（準拠率・強み・改善点・トレードオフ）
- [report-template/architecture.html](report-template/architecture.html): インライン SVG のシステム構成図

下記はピラー詳細の内容イメージ（Markdown 表記）です。

```markdown
## コスト最適化 (Cost Optimization)
- 準拠率: 76%（19/25 項目）🟡 要改善

### できている点（強み）
- 予約割引を一部の VM に適用済み
- 開発環境に自動シャットダウンを設定済み

### 改善点
| 優先度 | 対象 | 指摘 | 推奨アクション | トレードオフ | 根拠（参考） |
| --- | --- | --- | --- | --- | --- |
| 中 | Log Analytics | 日次取り込み上限が未設定 | Daily Cap を設定 | 監視データ欠損のリスク（運用性と相反） | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
| 低 | Managed Disk | 未使用ディスク | 削除またはスナップショット化 | 復旧元データを失う可能性 | [WAF: コスト最適化](https://learn.microsoft.com/azure/well-architected/cost-optimization/) |
```

> 生成されたレポートは `reports/<YYYYMMDD-HHmmss>/` に保存されます（`index.html`＋選択した各ピラー＋`architecture.html`＋`findings.json`＋`progress.md`）。同日複数回でも上書きされません。中間 `.work/` は統合後に削除されます。このフォルダは `.gitignore` 済み（ローカル限定）のため、レポート内ではプレースホルダではなく **実際の ID・リソース名** を記載します（上記のサンプルは公開用のため一般化）。シークレット等の機微情報はローカルでも記載しません。

## 注意事項

- 本ユースケースは **読み取り専用の分析** を前提とし、破壊的操作は行わない。実施する場合はユーザーが内容を確認したうえで別途対応すること。
- **リポジトリにコミットするドキュメント/サンプル**には実 ID・リソース名・個人情報・シークレットを含めず、プレースホルダを使用する（`reports/` のローカルレポートは実値可。ただしシークレットや個人のメール等の PII は記載しない）。
- コスト値やメトリクスは環境・期間により変動するため、あくまで目安として扱う。

## 参考リンク

- [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/)
- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/)

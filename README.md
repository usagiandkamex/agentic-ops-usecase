# agentic-ops-usecase

**Agentic IT Ops** のユースケースと、それを実現する GitHub Copilot エージェント（カスタムチャットモード・プロンプト・インストラクション）を集約する Public リポジトリです。

IT 運用（Ops）の実務課題を、GitHub Copilot を中心としたエージェントでどう解決するかを、再利用可能な形でまとめることを目的としています。対象システムとして Azure を想定するケースを含みます。

## 🎯 目的

- IT Ops の具体的なユースケースを、手順とエージェント定義つきで蓄積する。
- GitHub Copilot（VS Code のカスタムチャットモード / プロンプト / インストラクション）で再現できる形にする。
- 誰でも参照・再利用できるよう、公開前提で機密情報・個人情報を含めずに整備する。

## 📁 リポジトリ構成

```text
.
├── README.md                       このファイル(概要とユースケース索引)
├── LICENSE                         MIT ライセンス
├── CONTRIBUTING.md                 コントリビューションガイド
├── .github/                        VS Code が自動検出するエージェント群
│   ├── copilot-instructions.md     リポジトリ共通の Copilot 指針
│   ├── agents/                     カスタムエージェント (<NNN>-*.agent.md)
│   ├── prompts/                    プロンプト (<NNN>-*.prompt.md)
│   └── instructions/               インストラクション (<NNN>-*.instructions.md)
├── .vscode/
│   └── mcp.json                    MCP サーバの定義 (Azure MCP / MRC・共有用・オプトイン)
├── docs/
│   └── usecase-template.md         ユースケースの雛形
└── usecases/
    ├── 001-azure-resource-analysis/       ユースケースの説明・索引(README)
    ├── 002-config-inventory-vulnerability/ ユースケースの説明・索引(README)
    ├── 003-network-access-evaluation/      ユースケースの説明・索引(README)
    └── 004-availability-report/            ユースケースの説明・索引(README)
```

> エージェントの実体は VS Code の自動検出仕様に合わせ `.github/` 配下に置き、`<NNN>-` プレフィックスでユースケースを紐付けます。`usecases/<NNN>-<name>/README.md` は人が読むドキュメント（索引）です。

## 📚 ユースケース一覧

| ユースケース | 概要 | リンク |
| --- | --- | --- |
| 001 Azure リソース分析 | Azure Well-Architected Framework の5本柱（信頼性・セキュリティ・コスト最適化・オペレーショナルエクセレンス・パフォーマンス効率）で Azure リソースを分析する | [usecases/001-azure-resource-analysis](usecases/001-azure-resource-analysis/README.md) |
| 002 構成管理棚卸・脆弱性検知 | 利用者責任リソースの OS/ランタイム/エンジン版数を読み取り専用で棚卸し、公開脆弱性情報（Defender の CVE・EOL）と照合して是正要否・パッチ適用可否を判定する | [usecases/002-config-inventory-vulnerability](usecases/002-config-inventory-vulnerability/README.md) |
| 003 ネットワークアクセス可否評価 | 対象リソース × パブリック IP/URL × 方向（インバウンド/アウトバウンド）の通信可否を、経路上の全制御レイヤ（NSG / App Service アクセス制限 / Azure Firewall+UDR / 境界 / PaaS FW）で読み取り専用に横断判定し、期待状態への変更提案（az/Bicep）を提示する | [usecases/003-network-access-evaluation](usecases/003-network-access-evaluation/README.md) |
| 004 Azure 定期稼働報告 | IPA「非機能要求グレード2018」の可用性・運用保守性項目に基づき、指定期間の可用性・SLA 達成状況・稼働率・インシデント・運用点検を読み取り専用で集計し、定期稼働報告を自動生成する | [usecases/004-availability-report](usecases/004-availability-report/README.md) |

> 新しいユースケースを追加したら、この表に1行追記してください。

## 🚀 使い方

1. 目的に近いユースケースを上の一覧から選び、その `README.md` を開く。
2. VS Code の GitHub Copilot Chat で対応するエージェント（`.github/agents/`）を選択する。
3. `/` コマンドでプロンプト（`.github/prompts/`）を実行し、インストラクションの指針に沿って分析・運用を進める。

> VS Code でカスタムチャットモード（`.chatmode.md`）やプロンプトファイル（`.prompt.md`）を利用するには、GitHub Copilot 拡張機能が必要です。

## 🔒 公開ポリシー

本リポジトリは **Public** です。サブスクリプション ID・テナント ID・リソース名・個人情報・シークレット等の実値は含めず、必ずプレースホルダを使用してください。詳細は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 🤝 コントリビューション

新しいユースケースの追加や改善を歓迎します。手順は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 📜 ライセンス

[MIT License](LICENSE) の下で公開されています。
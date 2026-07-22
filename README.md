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
├── .github/
│   └── copilot-instructions.md     リポジトリ共通の Copilot 指針
├── docs/
│   └── usecase-template.md         ユースケースの雛形
└── usecases/
    └── azure-resource-analysis/    ユースケース: Azure リソース分析
        ├── README.md
        ├── agents/                 カスタムチャットモード (*.chatmode.md)
        ├── prompts/                プロンプトファイル (*.prompt.md)
        └── instructions/           インストラクション (*.instructions.md)
```

## 📚 ユースケース一覧

| ユースケース | 概要 | リンク |
| --- | --- | --- |
| Azure リソース分析 | 費用・セキュリティ・信頼性・パフォーマンス・アラートの5観点で Azure リソースを分析する | [usecases/azure-resource-analysis](usecases/azure-resource-analysis/README.md) |

> 新しいユースケースを追加したら、この表に1行追記してください。

## 🚀 使い方

1. 目的に近いユースケースを上の一覧から選び、その `README.md` を開く。
2. `agents/` のチャットモードを VS Code の GitHub Copilot Chat で選択する。
3. `prompts/` のプロンプトファイルを実行し、`instructions/` の指針に沿って分析・運用を進める。

> VS Code でカスタムチャットモード（`.chatmode.md`）やプロンプトファイル（`.prompt.md`）を利用するには、GitHub Copilot 拡張機能が必要です。

## 🔒 公開ポリシー

本リポジトリは **Public** です。サブスクリプション ID・テナント ID・リソース名・個人情報・シークレット等の実値は含めず、必ずプレースホルダを使用してください。詳細は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 🤝 コントリビューション

新しいユースケースの追加や改善を歓迎します。手順は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 📜 ライセンス

[MIT License](LICENSE) の下で公開されています。
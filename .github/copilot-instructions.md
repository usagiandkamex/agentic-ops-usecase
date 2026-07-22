---
applyTo: '**'
---

# リポジトリ共通 Copilot 指針

本リポジトリ `agentic-ops-usecase` は、GitHub Copilot を中心とした **Agentic IT Ops** の
ユースケースとエージェント定義を集約する **Public リポジトリ** です。

## 言語

- ドキュメント（README・説明文）は **日本語** で記述する。
- コードやスクリプト内のコメントは **英語** を基本とする。

## セキュリティ / 公開ポリシー（最重要）

- 本リポジトリは公開されている。**機密情報・個人情報（PII）を絶対に含めない**。
- サブスクリプション ID・テナント ID・リソース名・IP・メールアドレス・シークレット等は
  実値を書かず、必ずプレースホルダ（`<SUBSCRIPTION_ID>`, `<TENANT_ID>`,
  `<RESOURCE_GROUP>`, `<RESOURCE_NAME>`, `<REGION>` など）を使用する。
- 機密値はローカルの `.env` / `appsettings.local.json` 等に置き、`.gitignore` で除外する。

## Azure 操作の方針

- Azure リソースの照会・分析は **Azure MCP ツールを優先** して利用する。
- Azure MCP が利用できない場合は **Azure CLI (`az`)** を代替として提示する。
- 破壊的操作（削除・変更・デプロイ）は実行前に必ずユーザーへ確認する。
- 既定では **読み取り専用（分析）** を前提とする。

## リポジトリ構成

- `docs/` : 共通ドキュメントとユースケース雛形。
- `usecases/<name>/` : ユースケース単位。`agents/`（チャットモード）、
  `prompts/`（プロンプト）、`instructions/`（インストラクション）を含む。

## 執筆スタイル

- 簡潔・実用的に。手順は番号付きリスト、観点は箇条書きで示す。
- 新規ユースケースは [docs/usecase-template.md](../docs/usecase-template.md) に従う。

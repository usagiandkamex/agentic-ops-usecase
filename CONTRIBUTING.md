# コントリビューションガイド

`agentic-ops-usecase` へのご協力ありがとうございます。本リポジトリは **Agentic IT Ops**（GitHub Copilot を中心としたエージェント活用）のユースケースとエージェント定義を集約する **Public リポジトリ** です。以下のルールを守ってご参加ください。

## 🔒 最重要: 機密情報・個人情報を含めない

本リポジトリは公開されています。次の情報は **絶対にコミットしないでください**。

- サブスクリプション ID / テナント ID / オブジェクト ID などの実 GUID
- リソース名・アカウント名・ホスト名・IP アドレスなど実環境を特定できる値
- 個人名・メールアドレス・電話番号などの個人情報（PII）
- API キー・接続文字列・シークレット・トークン・証明書
- 顧客データや社内限定の情報

これらを記載する必要がある場合は、必ず **プレースホルダ** を使用してください。

| 種別 | プレースホルダ例 |
| --- | --- |
| サブスクリプション ID | `<SUBSCRIPTION_ID>` |
| テナント ID | `<TENANT_ID>` |
| リソースグループ | `<RESOURCE_GROUP>` |
| リソース名 | `<RESOURCE_NAME>` |
| リージョン | `<REGION>` |

機密値はローカルの `.env` や `appsettings.local.json` に置き、`.gitignore` で除外されていることを確認してください。

## 📁 ディレクトリ構成

```text
docs/                          共通ドキュメント・テンプレート
usecases/<usecase-name>/       ユースケース単位のフォルダ
  README.md                    ユースケースの説明
  agents/                      カスタムチャットモード (*.chatmode.md)
  prompts/                     プロンプトファイル (*.prompt.md)
  instructions/                インストラクション (*.instructions.md)
```

## ➕ 新しいユースケースの追加手順

1. [docs/usecase-template.md](docs/usecase-template.md) をコピーして `usecases/<usecase-name>/README.md` を作成する。
2. 必要なエージェント（`.chatmode.md`）・プロンプト（`.prompt.md`）・インストラクション（`.instructions.md`）を追加する。
3. ルートの [README.md](README.md) の「ユースケース一覧」に項目を追記する。
4. コミット前に機密情報が含まれていないか確認する（下記チェックを推奨）。

```powershell
# 実 GUID が含まれていないかの簡易チェック (PowerShell)
Select-String -Path .\usecases\**\*, .\docs\**\* -Pattern '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
```

## ✍️ スタイル

- ドキュメントは **日本語**、コード内コメントは **英語** を基本とする。
- Markdown の見出し・箇条書きを活用し、簡潔に記述する。
- ファイル/ディレクトリ名はケバブケース（例: `azure-resource-analysis`）。

## 📜 ライセンス

本リポジトリへのコントリビューションは [MIT License](LICENSE) の下で公開されることに同意したものとみなされます。第三者の著作物を含める場合は、ライセンス上問題がないことを必ず確認してください。

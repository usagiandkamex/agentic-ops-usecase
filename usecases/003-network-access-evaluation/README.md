# ユースケース: ネットワークアクセス可否評価

## 概要

Azure 上に構築したシステム（VM・App Service・API Management など）を対象に、**あるパブリック IP / URL** と **通信方向（インバウンド / アウトバウンド）**（必要に応じてポート / プロトコル）を入力として、その通信が現状 **「許可」か「拒否」か** を、経路上の全制御レイヤ（NSG・App Service アクセス制限・API Management の ip-filter・Azure Firewall + ルートテーブル・境界サービス・PaaS ファイアウォール）を **読み取り専用** で横断評価して判定します。さらに期待状態（許可したい / 拒否したい）に対して **「何を判断すればよいか」** のチェックリストと、具体的な変更案（Azure CLI / Bicep）を提示します。**構成変更の実行は行わず、提案までに留めます。**

運用中のシステムで **情報ソースの追加やアクセス元 IP の追加** が発生した際に、これを用いて現状の可否を確認し、必要であれば提案に基づいて構成変更を判断・実施するためのユースケースです。

## 背景 / 課題

- 運用中システムでは、連携先の追加・アクセス元 IP の追加のたびに「その通信が通るか / 塞がっているか」を確認する必要がある。
- 可否は NSG・Azure Firewall・App Service アクセス制限・API Management の ip-filter・ルートテーブル・PaaS ファイアウォールなど **複数レイヤの規則の重ね合わせ** で決まり、手作業での追跡は煩雑で属人化・見落としが生じやすい。
- 「許可したい / 拒否したい」を実現するために、どのレイヤの何を変えるべきか・何を判断すべきかを、根拠付きで再現性高く整理したい。

## 目的 / 期待効果

- 指定した **リソース × IP/URL × 方向** の通信可否を、経路上の各レイヤの一致規則と根拠付きで判定する。
- 期待状態と現状のギャップを分析し、**何を判断すべきか（考慮事項チェックリスト）** と **具体的な変更案（az / Bicep）** を提示する。
- 運用変更（ソース追加・IP 追加）時の確認・意思決定のリードタイムとレビュー負荷を下げる。

## 前提条件

- 対象リソース / ネットワークリソースに対する **Reader（読み取り）権限**。追加の書き込み権限は不要（本ユースケースは書き込みを行わない）。
- 分析基盤として **Azure MCP ツール** が利用できること（推奨）。利用できない場合は **Azure CLI (`az`)** の照会系コマンドや **Azure Resource Graph** を代替として使用する。
  - 利用前に `az account show` で認証状態を確認し、未認証なら **`az login`** で Azure に認証する。
- URL を入力する場合、**DNS 解決**（`Resolve-DnsName`）でグローバル IP を得るためのインターネット接続。
- VS Code + GitHub Copilot 拡張機能。

> 本ユースケースは **読み取り専用（READ 操作のみ）** です。NSG / ファイアウォール / アクセス制限の変更・削除・追加など、リソースへの書き込みに相当する操作は一切行いません。構成変更は **提案（az / Bicep のコード提示）に留め**、実施はユーザーに委ねます。

## 利用するエージェント

実体は VS Code が自動検出する `.github/` 配下に `003-` プレフィックス付きで配置する。本ユースケースは **オーケストレーター ＋ 3 サブエージェント（収集 / 判定 / レポート生成）** の 4 エージェント構成。

| 種別 | ファイル | VS Code での呼び出し | 役割 |
| --- | --- | --- | --- |
| エージェント（オーケストレーター） | [.github/agents/003-network-access-analyst.agent.md](../../.github/agents/003-network-access-analyst.agent.md) | エージェント選択 `azure-network-access-analyst` | 入力対話確認・リソース決定論解決・URL→DNS 解決・収集能力判別・単一承認取得・委譲・完了報告 |
| サブエージェント（経路収集） | [.github/agents/003-network-path-collector.agent.md](../../.github/agents/003-network-path-collector.agent.md) | 自動委譲（user-invocable:false） | 経路上の全制御レイヤ構成を READ 収集し `findings.json` の `target` / `pathLayers[].rulesEvaluated` を確定（**判定はしない**）。質問ツール非搭載で無停止・並列完走 |
| サブエージェント（可否判定・提案） | [.github/agents/003-network-access-evaluator.agent.md](../../.github/agents/003-network-access-evaluator.agent.md) | 自動委譲（user-invocable:false） | 収集済み構成＋query から レイヤ別許可/拒否・総合判定（AND）・ギャップ分析・変更提案（az/Bicep）を確定。質問ツール非搭載 |
| サブエージェント（レポート生成） | [.github/agents/003-network-report-writer.agent.md](../../.github/agents/003-network-report-writer.agent.md) | 自動委譲（user-invocable:false） | `findings.json` を唯一のデータ源に HTML 4 ページ＋CSV を生成し検証ゲート・独立レビュー。質問ツール非搭載 |
| インストラクション | [.github/instructions/003-network-access.instructions.md](../../.github/instructions/003-network-access.instructions.md) | 自動適用 | READ 専用・同意・機密ポリシー・テンプレ機構・判定モデルなどの共通ルール |
| プロンプト（インバウンド確認） | [.github/prompts/003-inbound-access-check.prompt.md](../../.github/prompts/003-inbound-access-check.prompt.md) | `/azure-inbound-access-check` | 指定 IP/URL からの **インバウンド** 通信可否を評価 |
| プロンプト（アウトバウンド確認） | [.github/prompts/003-outbound-access-check.prompt.md](../../.github/prompts/003-outbound-access-check.prompt.md) | `/azure-outbound-access-check` | 対象から指定 IP/URL への **アウトバウンド** 通信可否を評価 |
| プロンプト（変更提案） | [.github/prompts/003-change-proposal.prompt.md](../../.github/prompts/003-change-proposal.prompt.md) | `/azure-network-change-proposal` | 期待状態に対する判断チェックリストと変更案（az/Bicep）を提示 |

## 手順

エージェントは次の **番号手順（1 → 7）** を順に実行し、各手順の自己チェックを経て次に進みます。判定（手順 5）とレポート生成（手順 6）・最終レビュー（手順 7）は分離し、公正な判定・レビューを行います。

> **オーケストレーター＋3 サブエージェント構成（確認は 1 回・以降無停止）**: オーケストレーターが **①入力対話確認・リソース決定論解決・URL→DNS 解決 → ②収集能力判別 → ③単一承認 → ④承認** を行い、承認後は **⑤ collector（経路収集）→ ⑥ evaluator（可否判定・提案）→ ⑦ report-writer（HTML/CSV 生成・検証）** へ委譲し、**完了報告** します。3 サブエージェントは質問ツールを持たないため、承認後は途中でユーザーに聞けず順序も変えられず **無停止で完走** します。

1. VS Code の GitHub Copilot Chat で、エージェント **`azure-network-access-analyst`** を選択する。
2. **入力確認・同意**: 対象リソース（テナント / サブスクリプション / RG / リソース名）、**パブリック IP または URL**、**方向（インバウンド / アウトバウンド）**、任意で **ポート / プロトコル**、**期待状態（許可したい / 拒否したい / 現状確認のみ）** を対話で確認する。URL の場合は DNS 解決して IP を確定し、承認画面に提示する。
3. **収集能力の判別**: リソース種別から関係する経路レイヤ（NSG・App Service アクセス制限・API Management（ip-filter / VNet）・Azure Firewall + ルートテーブル・境界・PaaS）を特定し、READ で参照可能かを判別する。
4. **経路収集**: 各レイヤの構成（NSG 規則・ルートテーブル・ファイアウォール規則・アクセス制限・公開状況）を READ 専用で収集し `findings.json` に整理する。
5. **可否判定・ギャップ分析・提案**: 各レイヤで IP/方向/ポートが許可されるかを優先度・precedence を考慮して評価し、総合判定（全レイヤ AND）を確定する。期待状態とのギャップを分析し、担当レイヤ別に判断チェックリストと変更案（az/Bicep）を生成する。
6. **レポート生成・保存**: HTML 4 ページ（index / evaluation / proposal / architecture）＋ CSV（evaluated-rules）＋ `findings.json` を生成し `reports/` に保存する。
7. **最終レビュー**: 生成と分離した公正なレビューを行い、不備があれば修正・再生成する。

フェーズ別プロンプト（`/azure-inbound-access-check` / `/azure-outbound-access-check` / `/azure-network-change-proposal`）を個別に実行することもできます。

## 出力例

```text
対象: <RESOURCE_NAME>（Microsoft.Compute/virtualMachines）
クエリ: 送信元 <SOURCE_IP> → インバウンド / TCP 443
総合判定: 拒否（Denied）
一致レイヤ: NSG(subnet=<SUBNET_NAME>) の既定拒否規則 DenyAllInbound (priority 65500)
根拠: 明示的な許可規則が無く、既定の全拒否に一致

期待状態: 許可したい
ギャップ: 現状「拒否」→ 期待「許可」（担当レイヤ: NSG(subnet)）
判断すべきこと（抜粋）:
  - 送信元は単一 IP か CIDR か（最小範囲で許可する）
  - ポート/プロトコルを 443/TCP に限定できるか
  - サービスタグ（例: AzureFrontDoor.Backend）で代替できないか
  - 既存規則の優先度と衝突しないか
変更案（az / Bicep）: 別紙 proposal.html を参照
```

## 注意事項

- 本ユースケースは **読み取り専用**。設定変更・削除・追加は行わず、可否判定と変更提案（コード提示）に留める。
- 判定は収集時点の構成に基づく静的評価であり、アプリ層の認証・WAF ルール・OS 内ファイアウォール等は評価対象外（別途考慮が必要な場合は提案に明記する）。
- 実 ID / リソース名 / IP / 個人情報 / シークレットを含めないこと（生成レポートは `reports/` 配下・`.gitignore` 済みのローカル限定）。

## 参考リンク

- [Azure ネットワーク セキュリティ グループ (NSG)](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)
- [App Service アクセス制限](https://learn.microsoft.com/azure/app-service/overview-access-restrictions)
- [API Management の IP フィルターポリシー（ip-filter）](https://learn.microsoft.com/azure/api-management/api-management-access-restriction-policies#RestrictCallerIPs)
- [API Management の仮想ネットワーク構成（VNet）](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)
- [Azure Firewall のルール処理ロジック](https://learn.microsoft.com/azure/firewall/rule-processing)
- [ルートテーブルと UDR](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview)

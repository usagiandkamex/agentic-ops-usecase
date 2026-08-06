---
name: 'azure-inbound-access-check'
description: '指定したパブリック IP / URL から Azure 上の対象リソースへの インバウンド 通信が現状「許可」か「拒否」かを、経路上の全制御レイヤで読み取り専用に横断評価する。'
agent: 'azure-network-access-analyst'
---

# インバウンド通信可否の評価（Inbound Access Check）

指定した **パブリック IP / URL**（アクセス元）から Azure 上の **対象リソース** への **インバウンド** 通信が
現状 **「許可」か「拒否」か** を、経路上の全制御レイヤ（境界 / Azure Firewall + ルートテーブル / NSG / App Service アクセス制限 / API Management（ip-filter / VNet）/ PaaS ファイアウォール）で
**READ 専用**に横断評価する。共通ルール・判定モデルはエージェント定義 [003-network-access-analyst.agent.md](../agents/003-network-access-analyst.agent.md) に従う。

## このプロンプトの位置づけ

- **方向**: `direction = Inbound`（アクセス元 IP/URL → 対象リソース）。
- **入力**: 対象リソース（テナント/サブスク/RG/リソース名）、アクセス元の **パブリック IP または URL**、任意で **ポート / プロトコル**、**期待状態**（許可したい=Allow / 拒否したい=Deny / 現状確認のみ=CheckOnly）。
- **出力**: `findings.json`（`overall.decision` = Allowed/Denied ほか）＋ HTML 4 ページ＋ `evaluated-rules.csv`。
- **READ 専用**（R1）: 構成変更は行わず、変更が必要な場合は **提案（az / Bicep のコード提示）** に留める。

## 実行（委譲・重要）

**本プロンプトのバインド先はオーケストレーター `azure-network-access-analyst`**。実処理は 3 サブエージェントへ委譲する
（① 入力確認・リソース決定論解決・URL→DNS 解決・収集能力判別 → ③ 単一承認 → ⑤ collector（経路収集）→ ⑥ evaluator（可否判定・提案）→ ⑦ report-writer（生成・検証）、の順）。
サブエージェントは質問ツールを持たないため承認後は**無停止で走り切る**。判定モデル・提案指針の正典は
[003-network-access-evaluator.agent.md](../agents/003-network-access-evaluator.agent.md)（本プロンプトには重複記載しない）。

## 入力の確認（曖昧時のみ質問）

- 必要入力（対象リソース・IP/URL・期待状態）に不足・曖昧があるときのみ確認する。**ポート/プロトコルは任意**で、未指定なら「全ポート前提」で評価する旨を伝える。
- URL 入力は **DNS 解決**してグローバル IP を確定し、承認画面に提示する（解決不可なら停止して確認）。

## 出力（`findings.json` の主な確定項目）

- `query`: `endpointInput` / `inputType`(IP/URL) / `resolvedIps[]` / `direction=Inbound` / `port` / `protocol` / `desiredState`。
- `pathLayers[]`: 各レイヤの `rulesEvaluated[]`（collector）＋ `matched` / `decision`（evaluator・Allow/Deny/NA）。
- `overall`: `decision`(Allowed/Denied) / `matchedLayer` / `reason`。`gap` / `proposals[]`（期待≠現状のときのみ）。
- **セクション保持**: 規則が 0 件・取得不可でも HTML のセクションは削除せず、「該当なし」/「確認不可（<制御> を READ 取得できませんでした）」を明示する。

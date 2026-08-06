---
name: 'azure-outbound-access-check'
description: 'Azure 上の対象リソースから指定したパブリック IP / URL への アウトバウンド 通信が現状「許可」か「拒否」かを、経路上の全制御レイヤで読み取り専用に横断評価する。'
agent: 'azure-network-access-analyst'
---

# アウトバウンド通信可否の評価（Outbound Access Check）

Azure 上の **対象リソース** から指定した **パブリック IP / URL**（宛先）への **アウトバウンド** 通信が
現状 **「許可」か「拒否」か** を、経路上の全制御レイヤ（NSG アウトバウンド / Azure Firewall + ルートテーブル（FQDN ルール含む）/ 境界 / PaaS）で
**READ 専用**に横断評価する。共通ルール・判定モデルはエージェント定義 [003-network-access-analyst.agent.md](../agents/003-network-access-analyst.agent.md) に従う。

## このプロンプトの位置づけ

- **方向**: `direction = Outbound`（対象リソース → 宛先 IP/URL）。
- **入力**: 対象リソース（テナント/サブスク/RG/リソース名）、宛先の **パブリック IP または URL**、任意で **ポート / プロトコル**、**期待状態**（許可したい=Allow / 拒否したい=Deny / 現状確認のみ=CheckOnly）。
- **出力**: `findings.json`（`overall.decision` = Allowed/Denied ほか）＋ HTML 4 ページ＋ `evaluated-rules.csv`。
- **READ 専用**（R1）: 構成変更は行わず、変更が必要な場合は **提案（az / Bicep のコード提示）** に留める。

## 実行（委譲・重要）

**本プロンプトのバインド先はオーケストレーター `azure-network-access-analyst`**。実処理は 3 サブエージェントへ委譲する
（① 入力確認・リソース決定論解決・URL→DNS 解決・収集能力判別 → ③ 単一承認 → ⑤ collector（経路収集）→ ⑥ evaluator（可否判定・提案）→ ⑦ report-writer（生成・検証）、の順）。
サブエージェントは質問ツールを持たないため承認後は**無停止で走り切る**。判定モデル・提案指針の正典は
[003-network-access-evaluator.agent.md](../agents/003-network-access-evaluator.agent.md)（本プロンプトには重複記載しない）。

## アウトバウンド固有の考慮

- 宛先が **URL/FQDN** の場合、DNS 解決した IP に加え、**Azure Firewall のアプリケーションルール（FQDN）** との整合も評価する（IP 化した宛先が NSG/ネットワークルールを通過しても FQDN ルールで許可/拒否され得る）。
- App Service など PaaS の送信は VNet 統合の有無で経路が変わる（統合時は NSG/UDR/Firewall を経由）。VNet 統合が無い場合、既定では送信制御が限定的である旨を注記する。

## 出力（`findings.json` の主な確定項目）

- `query`: `endpointInput` / `inputType`(IP/URL) / `resolvedIps[]` / `fqdn` / `direction=Outbound` / `port` / `protocol` / `desiredState`。
- `pathLayers[]`: 各レイヤの `rulesEvaluated[]`（collector）＋ `matched` / `decision`（evaluator）。
- `overall` / `gap` / `proposals[]`（期待≠現状のときのみ）。**セクション保持**: 0 件・取得不可でもセクションを残し「該当なし」/「確認不可」を明示する。

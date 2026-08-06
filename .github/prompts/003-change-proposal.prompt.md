---
name: 'azure-network-change-proposal'
description: '通信可否の判定結果を踏まえ、期待状態（許可したい / 拒否したい）を実現するために「何を判断すべきか」のチェックリストと、担当レイヤ別の変更案（az / Bicep）を読み取り専用で提示する。'
agent: 'azure-network-access-analyst'
---

# 変更提案（Network Change Proposal）

通信可否の判定結果（`findings.json` の `overall` / `pathLayers[]`）を踏まえ、期待状態（許可したい=Allow / 拒否したい=Deny）を実現するために
**「何を判断すべきか」** の考慮事項チェックリストと、担当レイヤ別の **変更案（az / Bicep）** を **READ 専用**で提示する。
**構成変更は提案（コード提示）に留め、実行しない**。共通ルール・提案指針はエージェント定義 [003-network-access-analyst.agent.md](../agents/003-network-access-analyst.agent.md) に従う。

## このプロンプトの位置づけ

- **対応手順**: エージェントの **手順 5（ギャップ分析・提案）** の focus。可否判定が未実施なら先に `/azure-inbound-access-check` または `/azure-outbound-access-check` を実行する。
- **入力**: 判定済み `findings.json`（`overall.decision` / `pathLayers[].decision`）と **期待状態**（`query.desiredState`）。
- **出力**: `findings.json` の `gap`（`meets` / `responsibleLayers[]`）と `proposals[]`（`considerations[]` / `changeSummary` / `azCli` / `bicep` / `tradeoff` / `reference`）＋ `proposal.html`。

## 実行（委譲・重要）

**本プロンプトのバインド先はオーケストレーター `azure-network-access-analyst`**。提案の実処理（gap / proposals 確定）は
**evaluator（`azure-network-access-evaluator`）へ委譲**する（オーケストレーターは自分で判定・提案を実行しない）。
提案指針の正典は [003-network-access-evaluator.agent.md](../agents/003-network-access-evaluator.agent.md)〈参照 P〉。

## 提案の原則

- **最小権限**: 送信元は最小範囲（単一 IP / 最小 CIDR）、ポート・プロトコルは対象に限定。可能なら **Service Tag** / **FQDN ルール** / **プライベートエンドポイント** で代替を提示する。
- **担当レイヤの特定**: 許可したい→現状「拒否」しているブロッカーとなる最初のレイヤ、拒否したい→現状「許可」しているレイヤのうち最小変更で塞げるレイヤ。
- **何を判断すべきか（considerations）**: 送信元は単一 IP か CIDR か / ポート・プロトコルを限定できるか / Service Tag・FQDN で代替できないか / 既存規則と優先度が衝突しないか / 変更管理・監査・承認フローが必要か / 一時的か恒久的か / 過剰公開（0.0.0.0/0）を避けられるか。
- **提案のみ**: `azCli` / `bicep` はコピー用の提案として格納し、**実行しない**。実 ID・実 IP を書く場合もローカル限定（`reports/` 配下）前提とし公開ファイルに転記しない。

## 出力（`findings.json`）

- `gap`: `desiredState` / `meets`(bool) / `responsibleLayers[]`。
- `proposals[]`: `layer` / `considerations[]` / `changeSummary` / `azCli` / `bicep` / `tradeoff` / `reference`。
- **セクション保持**: 期待状態を満たす、または `CheckOnly` のときは提案なし（`proposal.html` はフォールバック表示でセクションを残す）。

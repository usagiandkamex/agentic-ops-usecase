---
name: 'azure-inventory-collection'
description: 'Azure の対象 RG 内の全リソースを読み取り専用で棚卸し、OS/ランタイム/エンジン版数を findings.json に一覧化する。'
agent: 'azure-config-inventory-analyst'
---

# 構成管理棚卸（Inventory Collection）

対象の Azure テナント / サブスクリプション / RG 内の**全リソース**を **READ 専用**で棚卸し、
各リソースの **OS / ランタイム / エンジン版数**を `findings.json` に一覧化する。
共通ルール（READ 専用・出力仕様・カテゴリ等）はエージェント定義 [002-config-inventory-analyst.agent.md](../agents/002-config-inventory-analyst.agent.md) に従う。

## このプロンプトの位置づけ

- **対応手順**: エージェントの **手順 2（収集能力の判別）＋ 手順 3（棚卸収集）**。
- **入力**: 対象スコープ（テナント/サブスク/RG、単一 RG か全 RG か）。未指定なら〈参照 G〉例2 で確定 → 例1 で承認を得てから収集開始。
- **出力**: `findings.json` の `inventory[]` / `runtimeInventory[]`（後工程 4・5・6 へ引き継ぐ）。
- **READ 専用**（R1）: 照会系（get/list/show/query/GET）のみ。作成・変更・評価トリガー（`az vm assess-patches` 等）は行わない。

## やること

### 手順 2. 収集能力の判別

- (a) Resource Graph / ARM（常時可）、(b) Defender（`securityresources` に所見があるか）、(c) Update Manager（`patchassessmentresources` に評価結果があるか）を **照会で判別**する。
- (b)(c) が未構成・参照不可なら Resource Graph メタデータ＋EOL 照合中心のフォールバックに切り替える。
- 🔍 レビュー 2: 3 経路の可否を記録し限界を明示したか。判別がすべて READ か。

### 手順 3. 棚卸収集（`findings.json` を作りながら）

> 手順 3 冒頭で保存先 `reports/<YYYYMMDD-HHmmss>/` を決め、`report-template/findings.json` を複製した作業用 `findings.json` を **1 つだけ**作成し、収集の進行に合わせて逐次書き込む（別名 `findings-new.json` を作らない）。

1. **3-1 全列挙（権威ソース起点）**: `az resource list --subscription <SUBSCRIPTION_ID> --resource-group <RESOURCE_GROUP> -o json` を**権威ある全列挙**とし、全リソースを取得する。
   **Resource Graph 単独結果で「0 件」と即断しない**。0 件時は ① `az account show`（接続スコープ）② `az group show -n <RESOURCE_GROUP>`（RG 存在）③ `az graph query` と Azure MCP の group resource list で再列挙、の 3 経路で裏取りしてから結論づける。
2. **3-2 全リソースの登録と版数取得**: 全列挙を**すべて `inventory[]` に登録**する（`category` は機能別 8 分類。分類基準は〈参照 A〉）。
   版数・ランタイムの詳細は **★カテゴリ（Compute / AppRuntime / Container / Data）**を中心に、種別ごとの詳細照会（READ）で取得する（VM/VMSS のイメージ・osVersion・拡張機能、App Service の siteConfig、AKS の kubernetesVersion、マネージド DB の version 等。取得コマンドは〈参照 A〉）。
   **内部ランタイム・ソフトウェア**（対象は VM/VMSS と AKS/コンテナの内部のみ）は Defender ソフトウェアインベントリ
   `az graph query -q "securityresources | where type =~ 'microsoft.security/softwareinventories' | where id contains '<RESOURCE_GROUP>'"` で名称・版数・ベンダを抽出し `runtimeInventory[]` に格納する。
   **手順 2 で Defender for Cloud が「利用可」ならこの照会を必ず実行**して埋める（省略しない）。空になるのは実際に該当ソフトが無い場合のみで、`capabilityDetection` と矛盾させない（Defender=利用可なのに「MDVM 未有効」と書かない）。取得不可は「取得不可（Reader / MDVM 未有効）」と明示。
3. **3-3 並列化**: 対象が複数のときは詳細照会を並列に実行して短縮する（すべて READ のため安全。詳細は〈参照 E〉）。端末コマンドは 1 度に 1 本、並列化はコマンド内部のジョブで。

## 出力（`findings.json`）

- `inventory[]`（全リソース）: `resourceName, resourceType, category, issue, resourceGroup, location, osType, osOrImageVersion, runtimeOrEngine, runtimeVersion, extensionsOrImages, collectionSource, notes`
- `runtimeInventory[]`: `resourceName, resourceType, component, softwareName, version, vendor, source`
- `issue`（課題）は **手順 6 で確定**する（脆弱性照合・パッチ判定の結果を集約。基準は〈参照 B〉）。この段階では暫定でよい。
- `collectionSource` の例: `ResourceGraph` / `az` / `Defender` / `UpdateManager`。取得できない項目は「取得不可（Reader の範囲外）」と記載。
- 最終的に `inventory.csv` / `runtime-inventory.csv`（テンプレートをトークン置換して生成・UTF-8 BOM 付き）に反映される（生成は手順 6・出力仕様は〈参照 F〉）。

## レビュー 3（次工程前に必須）

- 権威列挙（`az resource list`）を起点にし、0 件時は接続スコープ＋3 経路で裏取り・根拠明記したか。
- 対象 RG 内の全リソースを `inventory[]` に登録し、★カテゴリの版数を取得したか。取得不可を明示したか。
- 収集操作がすべて READ だったか（書き込み・評価トリガーなし）。

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
- **入力**: 対象スコープ（テナント/サブスク/RG、単一 RG か全 RG か）。**テナント/サブスクの各入力トークンを GUID 正規表現で判定し、ID はそのまま環境で照合・名前は環境（`az account list` 等）から解決する（RG は常に名前・〈参照 L〉）**。一意に解決できたら例2 を省略し例1（最終確認）1 回で承認。名前が複数一致 / 0 件など一意に解決できないときだけ〈参照 G〉例2 で確定 → 例1 で承認を得てから収集開始。
- **出力**: `findings.json` の `inventory[]` / `runtimeInventory[]`（後工程 4・5・6 へ引き継ぐ）。
- **READ 専用**（R1）: 照会系（get/list/show/query/GET）のみ。作成・変更・評価トリガー（`az vm assess-patches` 等）は行わない。

## 実行（委譲・重要）

**本プロンプトのバインド先はオーケストレーター `azure-config-inventory-analyst`**。このフェーズの実処理（棚卸収集＝findings.json 確定）は **collector（`azure-inventory-collector`）へ委譲**して行い、**オーケストレーターは自分で収集・照合・判定を実行しない**（① スコープ解決 → ② 収集能力判別 → ③ 単一承認 → ⑤ collector へ委譲 → 収集ゲート G1〜G3 合格の検証、の順）。collector は質問ツールを持たないため承認後は**無停止・並列で走り切る**。**手順・判定基準・並列化/fetch 台帳・EOL/CVE のソース決定論ルーティングの正典は [002-inventory-collector.agent.md](../agents/002-inventory-collector.agent.md)**（本プロンプトには詳細を重複記載しない）。

## 出力（`findings.json`）

- `inventory[]`（全リソース）: `resourceName, resourceType, category, issue, resourceGroup, location, runtime, extensionsOrImages, collectionSource`（`runtime` は VM→OS / App Service 等→ランタイム / マネージド DB→DB エンジンの版数を単一列に集約）
- `runtimeInventory[]`: `resourceName, resourceType, component, softwareName, version, vendor, source`（VM・DB ホスト VM の DB エンジン・PaaS DB・App Service ランタイムを統合。`component`=`ospackage`/`language`/`middleware`/`dbengine`/`runtime` 等）
- `issue`（課題）は **手順 6 で確定**する（脆弱性照合・パッチ判定の結果を集約。基準は〈参照 B〉）。この段階では暫定でよい。
- `collectionSource` の例: `ResourceGraph` / `az` / `Defender` / `UpdateManager`。取得できない項目は「取得不可（Reader の範囲外）」と記載。
- 最終的に `inventory.csv` / `runtime-inventory.csv`（テンプレートをトークン置換して生成・UTF-8 BOM 付き）に反映される（生成は手順 6・出力仕様は〈参照 F〉）。
- **セクション保持（Issue #4）**: `runtimeInventory[]` が 0 件でも `inventory.html` の「ランタイム / ソフトウェア明細」セクションは削除せず残し、テンプレのフォールバック行で「該当なし」を表示する。Defender ソフトウェアインベントリ等が未有効・参照不可で取得できない場合は「確認不可（Defender / Update Manager 未有効）」と明示する（`findings.json` の配列は空配列のまま）。

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

### 手順 2. 収集能力の判別（サブ能力単位）

- (a) Resource Graph / ARM（常時可）、(b) Defender 推奨（`securityresources` の `assessments` に所見があるか）→`defenderForCloud`、(b2) Defender ソフトウェアインベントリ（`softwareinventories` に所見があるか・**MDVM は assessments と別能力**）→`defenderSoftwareInventory`、(c) Update Manager（`patchassessmentresources` に評価結果があるか）→`updateManager` を **照会で判別**する。
- **RG スコープ 0 件でも即『未構成』としない**: サブスク全体で 1 件でもあれば `利用可`（RG 内 0 件は該当なし）、サブスク全体でも 0 件なら `未構成`（機能未有効）。権限不足で照会自体が失敗したら `参照不可`。未構成・参照不可なら Resource Graph メタデータ＋EOL 照合中心のフォールバックに切り替える。
- 判別結果は手順 3 で作成する `findings.json` の `capabilityDetection`（`resourceGraph`/`defenderForCloud`/`defenderSoftwareInventory`/`updateManager`）に記録し、手順 3〜5 の実収集結果と照合する基準にする（整合性チェック・〈参照 I〉）。
- **必須収集タスクの materialize（収集し損ね防止・〈参照 J〉）**: **サブ能力ごと**に、`利用可`→`status:pending`、`未構成/参照不可`→`status:downgraded`（確認不可）で `collectionPlan[]` に登録する（常に `Inventory:azResourceList`(dueStep3)・`CVE:runtimeLookup`(dueStep4)・`CVE:osLookup`(dueStep5)、`defenderSoftwareInventory=利用可` → `Defender:softwareinventories`(dueStep3)、`defenderForCloud=利用可` → `Defender:assessments`(dueStep4)、`updateManager=利用可` → `UpdateManager:patchassessmentresources`(dueStep5)）。**Defender と Update Manager を同じ扱い**にする（CVE ルックアップは Web GET なので常時 pending）。以降、実行するたびに証跡付きで terminal 化し、切れ目ゲートで `pending` を 0 にしてから次へ進む。
- 🔍 レビュー 2: 4 サブ能力の可否を実データ有無で記録し限界を明示したか（RG 0 件時は off か該当なしを切り分けたか）。**`利用可` を `pending`、`未構成/参照不可` を `downgraded` で `collectionPlan[]` に登録したか**。判別がすべて READ か。

### 手順 3. 棚卸収集（`findings.json` を作りながら）

> 保存先 `reports/<YYYYMMDD-HHmmss>/` と `progress.md` は**エージェント起動直後（手順 1 前）に確定・作成済み**（〈参照 K〉）。手順 3 冒頭で `report-template/findings.json` を `read_file` で読みトークン置換した作業用 `findings.json` を `create_file` で **1 つだけ**作成し、収集の進行に合わせて逐次書き込む（別名 `findings-new.json` を作らない）。**照会 1 回ごとに対応配列へ追記し `collectionPlan[].evidence.resultCount` を更新、各手順末で期待件数＝実配列件数を照合する（まとめ書き禁止）。権威件数が 100 件を超えるときは `resourceId` を 100 件ずつのバッチに分割し、バッチ単位で収集→追記→`progress.md` のバッチ進捗を更新する（件数の正典は `az resource list` 全体）。** 以降 `progress.md` を**各手順の切れ目で更新・自己検査**してから次へ進む（〈参照 K〉）。テンプレは参照元で保存先に複製せず、**生成スクリプト（`.ps1`/`.py` 等）は作らず**既存更新は `replace_string_in_file` で行う（〈参照 K〉）。

1. **3-1 全列挙（`az resource list` を唯一の権威ソースに）**: `az resource list --subscription <SUBSCRIPTION_ID> --resource-group <RESOURCE_GROUP> -o json` を**唯一の権威ソース（single source of truth）**とし、その `id` 集合で棚卸対象を確定する。
   **件数の固定（実行セッション間でブレさせない）**: `inventory[]` の件数・`summary.totalResources` はこの権威件数と**必ず一致**させる。Resource Graph / Azure MCP は**版数などの詳細補完と 0 件裏取り専用**で件数を増減させない（正典は常に `az resource list`）。
   **Resource Graph 単独結果で「0 件」と即断しない**。0 件時は ① `az account show`（接続スコープ）② `az group show -n <RESOURCE_GROUP>`（RG 存在）③ `az graph query` と Azure MCP の group resource list で再列挙、の 3 経路で裏取りしてから結論づける。
2. **3-2 全リソースの登録と版数取得**: 権威リストを**すべて（漏れなく・重複なく）`inventory[]` に登録**する（`resourceId` で一意化。`category` は機能別 8 分類。分類基準は〈参照 A〉）。**登録直後に `inventory[]` の件数が `az resource list` の件数と一致することをその場で確認する**。
   **行を増やさない（件数固定）**: 詳細照会で得た子/プロキシ（subnet・NSG ルール・`az resource list` に現れない内部コンポーネント）を `inventory[]` の新規行にしない。版数は親行のフィールドか `runtimeInventory[]` に退避する（〈参照 I〉）。
   版数・ランタイムの詳細は **★カテゴリ（Compute / AppRuntime / Container / Data）**を中心に、種別ごとの詳細照会（READ）で取得する（VM/VMSS のイメージ・osVersion・拡張機能、App Service の siteConfig、AKS の kubernetesVersion、マネージド DB の version 等。取得コマンドは〈参照 A〉）。
   **ランタイム**（(A) VM/VMSS、(B) DB ホスト VM の DB エンジン、(C) PaaS マネージド DB の DB エンジン版数、(D) App Service/Functions/AKS ランタイムを同一表 `runtimeInventory[]`（7 列・列は増やさない）に統合）を READ で収集する。(A)(B) は Defender ソフトウェアインベントリ
   `az graph query -q "securityresources | where type =~ 'microsoft.security/softwareinventories' | where id contains '<RESOURCE_GROUP>'"` で名称・版数・ベンダを抽出、(C) は `az sql db show`/`flexible-server show` の version、(D) は siteConfig の linuxFxVersion 等（区分=`ospackage`/`language`/`middleware`/`dbengine`/`runtime` で識別）を `runtimeInventory[]` に格納する。
   **手順 2 で `defenderSoftwareInventory`（MDVM）が「利用可」ならこの照会を必ず実行**して (A)(B) を埋める（省略しない）。空になるのは **`defenderSoftwareInventory=利用可` で PaaS も含め実際に該当ソフトが無い場合のみ**（`empty-verified`）。**MDVM が `未構成/参照不可` なら (A)(B) は「確認不可（MDVM 未有効）」（`downgraded`）**と明示し、`empty-verified`（該当なし）と混同しない（(C)(D) の PaaS 版数は MDVM 非依存で取得可）。
3. **3-3 収集ウェーブ（並列化）**: 3-1 の権威リスト確定後、独立した 4 トラックを**並列**に実行して短縮する（すべて READ のため安全）。**Track A**: MDVM `softwareinventories` → `runtimeInventory[]`（(A)(B)）、**Track D**: VM/VMSS/PaaS/App Service/AKS 詳細（版数・siteConfig・kubernetesVersion）→ `inventory[]`/`runtimeInventory[]`（(C)(D)）はこの手順で着地。**Track B**（Defender `assessments`）/ **Track C**（Update Manager `patchassessmentresources`）は fetch を早期に並列開始してよいが着地検証は手順 4/5 のゲート（`dueStep`＝検証期限）で行う。Azure 詳細照会は **`ForEach-Object -Parallel -ThrottleLimit 5`**（`$using:`）でコマンド内並列、独立ツールは 1 ターンにまとめてバッチ並列。端末コマンドは 1 度に 1 本・**無制限並列は禁止**。**書き込みは親 Agent が直列**（worker は fetch のみ・配列ごとの安定キー〈参照 B〉で決定論マージ・同一ファイル多重書込みなし）。各トラックの `startedAt`/`endedAt`/`durationSec`/`resultCount`/`retryCount` を記録する（詳細は〈参照 E〉）。

## 出力（`findings.json`）

- `inventory[]`（全リソース）: `resourceName, resourceType, category, issue, resourceGroup, location, runtime, extensionsOrImages, collectionSource`（`runtime` は VM→OS / App Service 等→ランタイム / マネージド DB→DB エンジンの版数を単一列に集約）
- `runtimeInventory[]`: `resourceName, resourceType, component, softwareName, version, vendor, source`（VM・DB ホスト VM の DB エンジン・PaaS DB・App Service ランタイムを統合。`component`=`ospackage`/`language`/`middleware`/`dbengine`/`runtime` 等）
- `issue`（課題）は **手順 6 で確定**する（脆弱性照合・パッチ判定の結果を集約。基準は〈参照 B〉）。この段階では暫定でよい。
- `collectionSource` の例: `ResourceGraph` / `az` / `Defender` / `UpdateManager`。取得できない項目は「取得不可（Reader の範囲外）」と記載。
- 最終的に `inventory.csv` / `runtime-inventory.csv`（テンプレートをトークン置換して生成・UTF-8 BOM 付き）に反映される（生成は手順 6・出力仕様は〈参照 F〉）。
- **セクション保持（Issue #4）**: `runtimeInventory[]` が 0 件でも `inventory.html` の「ランタイム / ソフトウェア明細」セクションは削除せず残し、テンプレのフォールバック行で「該当なし」を表示する。Defender ソフトウェアインベントリ等が未有効・参照不可で取得できない場合は「確認不可（Defender / Update Manager 未有効）」と明示する（`findings.json` の配列は空配列のまま）。

## レビュー 3（次工程前に必須）

- `az resource list` を唯一の権威ソースにし、**`inventory[]` 件数が `az resource list` 件数（＝`summary.totalResources`）と一致**するか（実行セッション間でブレないか）。0 件時は接続スコープ＋3 経路で裏取り・根拠明記したか。
- 対象 RG 内の全リソースを `inventory[]` に登録し、★カテゴリの版数を取得したか。取得不可を明示したか。
- **件数照合・バッチ完了**: 各照会の期待件数（evidence の resultCount 合計）と `inventory[]`/`runtimeInventory[]` の実件数が一致するか（不一致は追記漏れとして補完）。100 件超は全バッチ（N/M）を完了したか。
- **整合性チェック**: 手順 2 の `capabilityDetection` と実収集結果が矛盾しないか（`defenderSoftwareInventory=利用可` なら `softwareinventories` を実収集、空なら再照会 → `empty-verified`（該当なし）or `downgraded`（確認不可）を確定）。MDVM 未有効を「該当なし」と混同していないか。食い違いを `consistencyChecks[]` に記録・解消したか（〈参照 I〉）。
- **切れ目ゲート G1（〈参照 J〉）**: `dueStep=3` のタスク（`Inventory:azResourceList`、`defenderSoftwareInventory=利用可` なら `Defender:softwareinventories`）が全て**証跡付きで terminal**（done/empty-verified/downgraded）か。`pending` が残っていれば手順 4 へ進まず、当該照会を実行する。`done` なのに `runtimeInventory[]` が空でないか。**消化後に `progress.md` の手順 3・G1 を更新したか（〈参照 K〉）。**
- 収集操作がすべて READ だったか（書き込み・評価トリガーなし）。
- **収集ウェーブの安全性**: 4 トラックの並列が READ 専用・`ThrottleLimit=5` で、書き込みは親 Agent 直列・決定論マージ（重複所見なし）だったか。各トラックに計時（`durationSec`/`retryCount` 等）を記録したか。

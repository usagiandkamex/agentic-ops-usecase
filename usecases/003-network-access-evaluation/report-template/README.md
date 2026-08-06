# レポートテンプレート（ユースケース 003）

**`azure-network-report-writer`（レポート生成サブエージェント）** はレポート生成時、このフォルダのテンプレートを **`read_file` で読み込み**、`findings.json` の実データで
`{{TOKEN}}` を置換した **完成ファイルを `create_file` で** `reports/<YYYYMMDD-HHmmss>/` に書き出します。
**`Copy-Item` 等のシェルコピーや外部スクリプト実行で作らない**（トークンが未置換のまま残る）。

> **フォルダ名 `<YYYYMMDD-HHmmss>`**: **JST（UTC+9）基準**の実際の実行時刻（秒精度）で命名し、各実行を区別する。
> 取得例（PowerShell）: `[DateTime]::UtcNow.AddHours(9).ToString('yyyyMMdd-HHmmss')`。

## 出力ファイル（3 種類の成果物＋進捗ファイル）

1. **HTML（人が読む・マルチページ）** — `report-template/*.html` を `read_file` で読み、トークン置換と BEGIN/END 行複製で完成させ `create_file` で生成:
   - [index.html](index.html) — 概要（メタ・評価対象クエリ・総合判定バッジ・サマリ件数・経路レイヤ別の判定・主な変更提案の抜粋・各ページへのタブリンク）
   - [evaluation.html](evaluation.html) — 経路評価（レイヤ別の適用可否・判定・一致規則、および評価した規則の明細）
   - [proposal.html](proposal.html) — 変更提案（期待状態とのギャップ、担当レイヤ別の「何を判断すべきか」チェックリストと変更案（az / Bicep）。**提案のみ・実行しない**）
   - [architecture.html](architecture.html) — 経路図（送信元 → 対象リソースの間で**実際に通過する制御レイヤ（許可/拒否）とノードのみ**を図示するホップ図。適用外（NA）の制御は図に描かず、「経路上に存在しない制御」セクション（not-on-path）に理由を文章で記載）
2. **CSV（機械可読データ）** — `{{RULE_ROWS}}` を全データ行に置換して生成（UTF-8 BOM 付き）:
   - [evaluated-rules.csv](evaluated-rules.csv) — 評価した全規則の明細（レイヤ・規則名・優先度・方向・アクション・プロトコル・送信元/宛先・ポート範囲・一致・レイヤ判定）
3. **[findings.json](findings.json)** — 中間データ（単一のデータ源）。HTML/CSV はこの実データで生成する。
   - `target` / `pathLayers[].rulesEvaluated` は **collector** が確定（READ 収集・判定はしない）。
   - `pathLayers[].matched` / `pathLayers[].decision` / `overall` / `gap` / `proposals` / `summary` は **evaluator** が確定（決定論の可否判定・ギャップ・提案）。
   - `consistencyChecks[]` は宣言（capabilityDetection）と実収集・判定の照合記録（HTML/CSV には出力しない中間データ・0 件でも配列は残す）。
4. **[progress.md](progress.md)** — 実行中の**進捗トラッキング**（ワークフロー遵守の強制）。**オーケストレーター（`azure-network-access-analyst`）が起動直後（手順 2 の入力確認より前）**に `read_file` で読み `create_file` で作成し（保存先フォルダもここで確定）、**各手順の切れ目（手順 1〜7・ゲート G0〜G3）で `replace_string_in_file` により更新・自己検査**してから次工程へ進む（オーケストレーターが手順 1〜3、`azure-network-path-collector` が手順 4・ゲート G0〜G1、`azure-network-access-evaluator` が手順 5・ゲート G2、`azure-network-report-writer` が手順 6〜7・ゲート G3 を更新）。`reports/` 配下のローカル成果物（コミットしない）。

## セクションの並び順（重要）

概要（index）→ **経路評価**（evaluation）→ **変更提案**（proposal）→ **経路図**（architecture）。

## 空セクションの扱い（該当なし / 確認不可・重要）

- **テンプレートのセクション（`<h2>`・テーブル・提案ブロック）は 0 件でも削除しない**。`<tbody>` を空のまま残さず、各テンプレ先頭コメントに記載の
  フォールバック行を **1 回だけ**出力してセクションを残す。
- **「該当なし」と「確認不可」を区別する**: 規則を READ 取得して実際に 0 件のときのみ「該当なし」。参照不可で判定・収集できない場合は「確認不可（<制御> を READ 取得できませんでした）」と明示する（`capabilityDetection` と矛盾させない）。
- **必須 SECTION アンカー**: index=`query`/`verdict`/`path-summary`/`top-proposal`、evaluation=`layer-summary`/`rule-detail`、proposal=`gap`/`proposals`、architecture=`path-diagram`/`not-on-path`。生成時に削除・改名せず出力に残す（消してよいのは先頭コメントブロックのみ）。欠落＝`<h2>` セクション削除として検証ゲートで不合格。
- **本ルールは HTML 限定**。CSV は 0 件ならヘッダ行のみ（合成レコードを追加しない）。`findings.json` の配列も空配列のままにする。index のサマリカード（件数）は 0 でも数値 `0` を表示する。

## 判定モデル（決定論・evaluator が適用）

- 各レイヤで、入力（解決 IP / 方向 / ポート・プロトコル）に一致する規則を **優先度順** に評価し、**最初に一致した規則**で許可 / 拒否を確定する（NSG は priority 昇順＋既定規則、Azure Firewall はルールコレクションの優先度、App Service アクセス制限は priority 昇順＋既定アクション、API Management は ip-filter を global→product→API→operation のスコープ順、PaaS ファイアウォールは許可リスト／既定拒否）。
- レイヤが対象リソースに存在しない場合は `applicable=false`・判定 `NA`（総合判定に影響しない）。
- **総合判定 = 全 applicable レイヤの AND**。いずれかのレイヤが `Deny` なら総合 `Denied`（最初の拒否レイヤを `overall.matchedLayer`）。全レイヤ `Allow` なら総合 `Allowed`。
- **ポート未指定**（`query.port=null`）のときは全ポート前提で評価し、レポートに「全ポート前提」と注記する。
- **desiredState** が `Allow`/`Deny` で現状（overall）と異なる場合のみ `gap.meets=false` とし、担当レイヤ別に `proposals[]`（考慮事項チェックリスト＋az/Bicep）を生成する。`CheckOnly` または期待を満たす場合は提案なし（フォールバック表示）。
- 提案は **最小権限**（送信元は最小範囲＝単一 IP / 最小 CIDR、ポート・プロトコルは限定、可能なら Service Tag / FQDN / プライベートエンドポイントで代替）を原則とする。az / Bicep は**コピー用の提案であり実行しない**。

## 生成手順（読み込み → 置換 → 検証ゲート）

1. `findings.json` テンプレを読み、`{{TOKEN}}` を実値に置換、各配列を実データ数だけ複製して `create_file` で書き出す（コメントキー `//` と `_example` は削除）。
2. 各 HTML テンプレを読み、`{{TOKEN}}` を置換、`<!-- BEGIN X -->`〜`<!-- END X -->` 区域は**内部の 1 行 / 1 ブロックを実データ件数分複製**して書き出す。**0 件でも `<h2>`・テーブルを削除しない／`<tbody>` を空にしない**——フォールバック行を **1 回だけ**出力する。先頭コメントを削除する。
3. `evaluated-rules.csv` テンプレを読み、ヘッダはそのまま `{{RULE_ROWS}}` を全データ行に置換する（**カンマ/改行/二重引用符を含む値は RFC 4180 で二重引用符囲み**）。
4. CSV を UTF-8 BOM 付きで再保存する。
5. **検証ゲート（必須・全合格まで確定しない）**: 「生成後チェック」を端末の READ コマンドで実行し、不合格なら当該ファイルを再生成して再検証する。

出力に `{{...}}` や `<!-- BEGIN/END -->` マーカー、テンプレート先頭コメントを残さないこと。

## CSV 行の生成ルール

- `evaluated-rules.csv`: `layer,ruleName,priority,direction,access,protocol,sourceOrDestination,portRange,matched,layerDecision`
  - `matched` は `はい`/`いいえ`。`layerDecision` は当該レイヤの判定（`Allow`/`Deny`/`NA`）。
  - 値にカンマ・改行・二重引用符を含む場合は二重引用符で囲み、内部の `"` は `""` にエスケープする（RFC 4180）。
  - 取得できない項目は空欄にせず「取得不可（Reader の範囲外）」と記載する。

## 対象範囲（経路レイヤ）

- **NSG**（サブネット / NIC・優先度・既定規則・ASG）、**App Service アクセス制限**（ipSecurityRestrictions / scmIpSecurityRestrictions・VNet 統合）、**API Management**（ip-filter ポリシー：global/product/API/operation スコープ・VNet モードの NSG・プライベートエンドポイント）、**Azure Firewall + ルートテーブル**（UDR 経由の経路・ネットワーク/アプリケーション（FQDN）ルール）、**境界**（Public IP・Load Balancer・Application Gateway・Front Door）、**PaaS ファイアウォール**（Storage/SQL 等のサービス FW・サービス/プライベートエンドポイント）。
- レイヤは評価順（送信元側 → 対象側）に `order` を付けて並べる。対象リソース種別に存在しないレイヤは `applicable=false`（判定 NA）。

## 機密 / 公開ポリシー

- `reports/` 配下はローカル限定（`.gitignore` 済み・コミットしない）。実 ID / 実 IP は生成レポートに記載してよいが、**シークレット / 接続文字列 / パスワードは記載しない**。
- 提案の az / Bicep に実 ID・実 IP を書く場合もローカル限定であることを前提とし、公開ファイル・コミット対象には転記しない。

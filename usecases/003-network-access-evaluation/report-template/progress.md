<!--
  progress.md テンプレート（ユースケース 003）— 実行中の進捗トラッキング（ワークフロー遵守の強制）
  役割: オーケストレーター（`azure-network-access-analyst`）が**起動直後（手順1の入力確認より前）**にこの雛形を read_file で読み、reports/<YYYYMMDD-HHmmss>/progress.md を create_file で作成し、
        各手順の「切れ目」で `replace_string_in_file` により更新・自己検査してから次工程へ進む（オーケストレーターが手順1〜3、`azure-network-path-collector` が手順4・ゲート G0〜G1、`azure-network-access-evaluator` が手順5・ゲート G2、`azure-network-report-writer` が手順6〜7・ゲート G3 を更新）。これにより手順スキップ・テンプレ改変・スクリプト生成などの逸脱を可視化して防ぐ。
  使い方:
  - 各項目のチェックボックスは、完了したらスペースを x に更新する（未完了のままにしない）。ゲートも完了で x にする。
  - 〈実行前の最終確認〉の承認取得は停止点ではない。承認後はオーケストレーターが同一ターン内で `azure-network-path-collector` 起動まで継続する。
  - 検証ゲート(手順6-3)は「未チェックのチェックボックスが 0 件」で完了を判定する。失敗・ブロッカーは末尾の記録欄に書く。
  - これは reports/<YYYYMMDD-HHmmss>/ 配下のローカル成果物（.gitignore 済み・コミットしない）。R2 の許可出力に含む。
  - この先頭コメントは作成後に必ず削除する（検証の誤検知を防ぐため）。
-->
# 実行進捗 — ネットワークアクセス可否評価

- 実行フォルダ: reports/<YYYYMMDD-HHmmss>/
- 開始(JST): <START_DATETIME>
- 対象: <TARGET_NAME>（<TARGET_TYPE>） / <RESOURCE_GROUP>（起動時は未確定でもよい。手順2確定後に更新）
- クエリ: <ENDPOINT_INPUT>（<INPUT_TYPE>）→ <DIRECTION> / <PORT> / <PROTOCOL> / 期待状態=<DESIRED_STATE>
- 現在地 / 次アクション: <例: 起動・progress.md 作成済。次は手順2 入力確認>

## 反スクリプト宣言（R2）
- [ ] findings.json / HTML / CSV を生成・整形する補助スクリプト（.ps1/.py/.sh 等）を作らない・実行しない
- [ ] 端末は Azure への READ 照会 / JST 時刻取得 / 認証確認 / DNS 解決（Resolve-DnsName）/ CSV の BOM 付与（1行 Set-Content）のみに使用
- [ ] 成果物は create_file（新規1回）＋ replace_string_in_file（既存更新）で直接書き出す

## 手順チェックリスト（1→7・順守）
- [ ] 起動直後 progress.md 作成・保存先 reports/<YYYYMMDD-HHmmss>/ 確定（手順2 の入力確認より前）
- [ ] 手順1 エージェント選択（`azure-network-access-analyst`）
- [ ] 手順2 入力確認・同意（対象リソース決定論解決／IP or URL／方向／ポート・プロトコル（任意）／期待状態・READ 専用明示。URL は DNS 解決して resolvedIps 確定）／レビュー2 OK
- [ ] 手順3 収集能力の判別（リソース種別から関係レイヤ NSG/AzureFirewall/AppService/PaaS/RouteTable を特定・READ 可否）／レビュー3 OK
- [ ] 〈実行前の最終確認〉承認取得（対象・クエリ・解決 IP・関係レイヤを提示）→ **承認後はターンを終了せず同一ターン内で手順4を開始（確認は停止点ではない）**
- [ ] 手順4 経路収集（collector・findings.json 作成・target/publicExposure 確定・pathLayers[].rulesEvaluated を READ 収集・判定はしない）／レビュー4 OK
- [ ] 手順5 可否判定・ギャップ分析・提案（evaluator・pathLayers[].matched/decision・overall（AND）・gap・proposals を確定）／レビュー5 OK
- [ ] 手順6 レポート生成（6-1 findings.json 確定 → 6-2 テンプレ読込置換 → 6-3 検証ゲート）／全合格
- [ ] 手順7 最終レビュー（独立レビュー全項目）／合格

## 収集・判定ゲート（切れ目ごと・完了で x）
- [ ] G0（手順3→4）: capabilityDetection に関係レイヤの可否を記録（利用可 / 未構成 / 対象外 / 参照不可）。対象リソースの publicExposure（Public IP / LB / AppGW / Front Door）を READ 確定
- [ ] G1（手順4→5）: pathLayers[] の全 applicable レイヤで rulesEvaluated を READ 取得済み（取得不可レイヤは reason に「確認不可」を明記）。collector は decision を確定しない（evaluator の責務）
- [ ] G2（手順5→6）: 全 applicable レイヤに matched/decision が確定・overall.decision が全レイヤ AND と整合・desiredState≠CheckOnly かつ meets=false なら proposals が 1 件以上・summary の各件数が pathLayers/proposals と一致
- [ ] G3（手順6-3・最終）: HTML 4 種＋evaluated-rules.csv＋findings.json＋progress.md のみ・未置換トークンや BEGIN/END 残存なし・SECTION アンカー全残存・CSV は UTF-8 BOM

## 収集の直列化・DNS 解決（R2）
- [ ] URL 入力時は Resolve-DnsName（または az/Web GET）でグローバル IP を解決し resolvedIps に記録（解決不可なら停止して確認）
- [ ] Azure 詳細照会は READ のみ（NSG 規則 show・route-table show・firewall policy show・app service config show・PaaS firewall-rule list 等）／端末は1度に1本
- [ ] findings.json への書き込みは直列（collector→evaluator の順で互いに素なセクションを更新・同一ファイルの多重並列書込みをしない）

## テンプレ準拠チェック（手順6・逐語複製の確認）
- [ ] テンプレは read_file で読む参照元（保存先に複製しない）。HTML を書き直さない
- [ ] 前回レポート・簡易版・記憶した HTML をベースに再構成していない（毎回テンプレを read_file した内容のみがベース）
- [ ] 各 HTML の `<style>` ブロック・`<header>` の `<span class="crumb">`・`<footer>` を削除・簡略化していない
- [ ] 各 HTML の `<h2>` セクションを 1 つも削除していない（0 件でもフォールバック行でセクションを残す）
- [ ] 各 HTML に必須 `<!-- SECTION: x -->` アンカーが全て残っている（index=query/verdict/path-summary/top-proposal、evaluation=layer-summary/rule-detail、proposal=gap/proposals、architecture=path-diagram）: <アンカー検査出力 不足 0 件>
- [ ] 各テーブルの <thead> 列がテンプレートと一致（列の新設・削除・改名なし）: <thead 検査 不一致 0 件>
- [ ] 判定ピルのクラスが dec-Allow/dec-Deny/dec-NA のみ・総合判定バッジが v-Allowed/v-Denied のみ（ラベル直書きなし）
- [ ] architecture.html の末尾に余分な矢印（&rarr;）が残っていない
- [ ] レポートフォルダに temp-*.* / 別名 findings-*.json が残っていない（成果物は HTML4/CSV1/findings.json/progress.md のみ）
- [ ] BEGIN/END 区域は対応配列の全要素を1行ずつ展開（省略・集約行なし）
- [ ] 出力に {{...}} / BEGIN/END マーカー / テンプレ先頭コメントが残っていない
- [ ] 検証ゲート 6-3 を実際に実行し、テーブル/footer/crumb/SECTION アンカー/BOM のコマンド出力を記録した: <検証出力の要約>
- [ ] evaluated-rules.csv が UTF-8 BOM 付き

## 逸脱・ブロッカー記録（あれば）
- （なし）

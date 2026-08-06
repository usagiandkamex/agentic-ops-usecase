<!--
  progress.md テンプレート（ユースケース 004）— 実行中の進捗トラッキング（ワークフロー遵守の強制）
  役割: エージェント(azure-availability-reporter)が**起動直後（手順1のスコープ確認より前）**にこの雛形を read_file で読み、reports/<YYYYMMDD-HHmmss>/progress.md を create_file で作成し、
        各手順の「切れ目」で `replace_string_in_file` により更新・自己検査してから次工程へ進む。手順スキップ・テンプレ改変・スクリプト生成などの逸脱を可視化して防ぐ。
  使い方:
  - 各項目のチェックボックスは、完了したらスペースを x に更新する（未完了のままにしない）。ゲートも完了で x にする。
  - 〈実行前の最終確認〉の承認取得は停止点ではない。承認後は同一ターン内で手順3以降を継続する（確認直後にターンを終了しない）。
  - 最終検証は「未チェックのチェックボックスが 0 件」で完了を判定する。失敗・ブロッカーは末尾の記録欄に書く。
  - これは reports/<YYYYMMDD-HHmmss>/ 配下のローカル成果物（.gitignore 済み・コミットしない）。
  - この先頭コメントは作成後に必ず削除する（最終検証の誤検知を防ぐため）。
-->
# 実行進捗 — 定期稼働報告

- 実行フォルダ: reports/<YYYYMMDD-HHmmss>/
- 開始(JST): <START_DATETIME>
- 対象: <SUBSCRIPTION_NAME> / <RESOURCE_GROUP>（起動時は未確定でもよい。手順1確定後に更新）
- 対象期間: <PERIOD_LABEL>（日次/週次/月次/カスタム・既定は前月の月次）
- 現在地 / 次アクション: <例: 起動・progress.md 作成済。次は手順1 スコープ・期間確認>

## 反スクリプト宣言（R2）
- [ ] findings.json / HTML / CSV を生成・整形する補助スクリプト（.ps1/.py/.sh 等）を作らない・実行しない
- [ ] 端末は Azure への READ 照会・JST 時刻取得・CSV の BOM 付与（1行 Set-Content）のみに使用
- [ ] 成果物は create_file（新規1回）＋ replace_string_in_file（既存更新）で直接書き出す

## 手順チェックリスト（1→7・順守）
- [ ] 起動直後 progress.md 作成・保存先 reports/<YYYYMMDD-HHmmss>/ 確定（手順1 のスコープ確認より前）
- [ ] 手順1 スコープ・対象期間・SLA目標入力の確認・同意（範囲=単一RG/サブスク全RG・対象=テナント/サブスク/RG・期間=日次/週次/月次/カスタム・SLA目標=sla-targets.csv の有無[未提供なら目標未入力として判定しない]）／レビュー1 OK
- [ ] 手順2 収集能力の判別（Resource Health / メトリック / アクティビティログ / アラート / バックアップ）／レビュー2 OK
- [ ] 〈実行前の最終確認〉承認取得 → **承認後はターンを終了せず同一ターン内で手順3を開始（確認は停止点ではない）**
- [ ] 手順3 データ収集（findings.json 作成・権威列挙[az resource list を直接実行]で対象確定・inventory[]/availability[]/incidents[]/alerts[] を逐次収集）／件数照合／レビュー3 OK
- [ ] 手順4 分析（稼働率算出・SLA 目標突合・SLA 判定・運用点検 operationsChecklist[]・slaSummary・非機能要求グレード紐付け nfrGradeMapping[]）／レビュー4 OK
- [ ] 手順5 レポート生成（テンプレ読込→トークン置換→BEGIN/END 行複製→HTML4/CSV2 書き出し）／レビュー5 OK
- [ ] 手順6 保存前レビュー（検証チェックリスト全項目）／全合格
- [ ] 手順7 保存・提示（reports/<YYYYMMDD-HHmmss>/ に確定・要約提示）

## 収集ゲート（切れ目ごと・pending を 0 にしてから次へ・完了で x）
- [ ] G0（手順2→3）: collectionPlan[] に全収集タスクを materialize（利用可→pending / 参照不可→downgraded）
- [ ] G1（手順3→4）: dueStep=3 タスク（authoritativeResourceEnumeration / ResourceHealth / Metrics / ActivityLog / Alerts）が全て証跡付き terminal（権威列挙が failed なら停止・レポート生成しない）
- [ ] G2（手順4→5）: dueStep=4 タスク（Ops:monitoringCoverage）が証跡付き terminal
- [ ] G3（手順6・最終）: collectionPlan[] に pending 0 件・failed 0 件・done→対象配列が非空

## テンプレ準拠チェック（手順5・6・逐語複製の確認）
- [ ] テンプレは read_file で読む参照元（保存先に複製しない）。HTML を書き直さない
- [ ] 前回レポート・簡易版・記憶した HTML をベースに再構成していない（毎回テンプレを read_file した内容のみがベース）
- [ ] 各 HTML の `<style>` ブロック・`<header>` の `<span class="crumb">`・`<footer>` を削除・簡略化していない
- [ ] 各 HTML の `<h2>` セクションを 1 つも削除していない（0 件でもフォールバック行でセクションを残す）
- [ ] 各 HTML に必須 `<!-- SECTION: x -->` アンカーが全て残っている（index=summary/top-incidents、availability=availability-method/availability-detail/sla-summary、incidents=incidents-list/alerts-list、operations=ops-checklist/nfr-mapping）: <アンカー検査出力 不足 0 件>
- [ ] 各テーブルの <thead> 列がテンプレートと一致（列の新設・削除・改名なし）: <thead 検査 不一致 0 件>
- [ ] BEGIN/END 区域は対応配列の全要素を1行ずつ展開（省略・「その他N件」集約行なし）
- [ ] 出力に {{...}} / BEGIN/END マーカー / テンプレ先頭コメントが残っていない
- [ ] CSV 2種（availability/incidents）が UTF-8 BOM 付き
- [ ] レポートフォルダの成果物が HTML4/CSV2/findings.json/progress.md のみ（temp-*/別名 findings-*.json なし）

## 逸脱・ブロッカー記録（あれば）
- （なし）

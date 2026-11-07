# 外出先の読み取り専用教材契約（public-v1）

[ADR 0001](../adr/0001-local-lan-and-remote-readonly-hosting.md) の外出先 Read-Only のうち、一般公開してよい教材を静的ファイルに書き出す範囲と形式を定める。

**2026-11-03 改訂（[#221](https://github.com/Yuki-Watanabe7/french-begginer/issues/221)）**: 2026-11-01 の簡素化（[#209](https://github.com/Yuki-Watanabe7/french-begginer/issues/209)）に合わせ、本人限定の private-v1、内容 hash の manifest と bundle hash による承認台帳、有効期限、Cloudflare Access を前提にした記述を外した。実装済みの `public-v1` の書き出しだけを正とする。

**2026-11-04 追記（[#222](https://github.com/Yuki-Watanabe7/french-begginer/issues/222)）**: 合成 Snapshot だけを同梱する独立した[静的ビューアー](readonly-viewer.md)を追加。公開（[#223](https://github.com/Yuki-Watanabe7/french-begginer/issues/223)）は未実装で、外部へ公開した教材はない。

**2026-11-05 追記（[#223](https://github.com/Yuki-Watanabe7/french-begginer/issues/223)）**: ビューアーと指定した教材だけを検査・梱包するローカルスクリプトと[公開・更新・停止の手順](public-readonly-publishing.md)を追加。GitHub Free / private repo では Pages を使えないため、2026-11-07 に所有者の判断で、このアプリ repo を public にして `gh-pages` ブランチから配布する方式にした（配布専用 repo は作らない）。repo の public 化、教材の送信、Pages 有効化はまだ行っていない。

## 読者と情報分類

`public-v1` は、誰でも JSON を取得・保存できる前提の一般教材である。LearningItem を採用したことは、公開や第三者配布の承認ではない。

| 元データ | public-v1 | 理由 |
|---|---|---|
| LearningItem の `item_type`、`canonical_form`、`meaning_ja`、`explanation_ja`、`level` | allowlist に載せた Item だけ出す | 閲覧に必要な最小限。内容は本人が確認する |
| LearningItem の `id`、`source_refs`（evidence を含む）、`metadata`、`status`、`created_at` | 出さない | 元 DB と結び付く ID や原文の位置を出さない。カード ID は配布内で新しく採番する |
| SourceDocument（本文・題名・URL・segments・provenance・metadata） | 出さない | 原文、私的な会話、出典の権利は公開対象にしない。出典表示もしない |
| Candidate、LearningEvent、LearnerState、ReviewSchedule、既知指定、苦手パターン | 出さない（読みもしない） | 学習履歴・due・weakness は個人データ |
| API キー、provider の応答、DB・バックアップ、log、音声・PDF | 出さない | 書き出すのはテキストの `snapshot.json` だけ |

本人限定の due / weakness の外部配布（旧 private-v1）は扱わない。必要になったら公開版とは分けて別 Issue で設計する。

## public-v1 の形式

1 ファイルの `snapshot.json`（UTF-8、整形済み JSON）。どの階層も下表以外のキーを持たず、任意項目は `null` にせず省く。ビューアーは文字列を HTML として解釈せず plain text で表示する。

| 階層 | キーと制約 |
|---|---|
| root | `schema_version` = `"public-v1"`、`generated_at` = UTC の RFC3339（`2026-11-03T09:30:00Z` の形。書き出した時刻で、DB の最終更新時刻ではない）、`cards` = 1–500 件 |
| card | `card_id` = `card-001` の形（allowlist の順に採番、重複なし）、`item_type` = `vocabulary` / `expression` / `grammar` / `conjugation`、`canonical_form`（問い）1–200 文字、`meaning_ja`（答え）1–500 文字、任意 `explanation_ja` 1–2,000 文字、任意 `level` = `A1`–`C2` |

型の正は [`backend/app/domain/public_snapshot.py`](../../backend/app/domain/public_snapshot.py) の `PublicSnapshot`。合成データだけで作った例が [public-snapshot.synthetic.json](public-snapshot.synthetic.json) で、exporter の出力と一致することをテストで確かめている。#222 の開発にはこれを使う。

`card_id` は書き出すたびの連番で、版をまたいで同じ教材を指す保証はない。

## 書き出し手順

1. 読む DB を決める。家庭内本番は `bash scripts/production_backup.sh` で取ったコピー（`~/FrenchTutorBackups/tutor-<時刻>.db`）を使い、稼働中の DB を直接読まない。開発 DB なら `backend/data/tutor.db`。
2. allowlist の下書きを作る。suspended 以外の全 Item が並ぶ。

   ```bash
   cd backend
   mkdir -p ~/FrenchTutorSnapshots
   uv run python ../scripts/export_public_snapshot.py draft \
     --database ~/FrenchTutorBackups/tutor-<時刻>.db \
     > ~/FrenchTutorSnapshots/allowlist.json
   ```

3. `allowlist.json` から、一般公開しない Item（人名、私的な会話の文、権利の不明な文など）を消す。並べた順がカードの順になる。`canonical_form` は取り違えを防ぐ確認値なので書き換えない。

   ```json
   {"items": [{"item_id": "<LearningItem の id>", "canonical_form": "bonjour"}]}
   ```

4. 書き出す。既定の出力先は `~/FrenchTutorSnapshots/public-<時刻>/snapshot.json` で、`--out` で変えられる。

   ```bash
   uv run python ../scripts/export_public_snapshot.py export \
     --database ~/FrenchTutorBackups/tutor-<時刻>.db \
     --allowlist ~/FrenchTutorSnapshots/allowlist.json
   ```

5. `snapshot.json` を全部読み、一般公開してよい内容だけか本人が確かめる。表示される sha256 は、公開するときに確認した版と同じかを照合するのに使う。外部への送信・公開はこの手順に含まない（#223）。

## 自動検査と、本人が確認すること

書き出しは次のどれかに当たると何も作らずに止まる。警告だけで続行はしない。エラーには値そのものを出さず、allowlist の何件目・どの項目かだけを出す。

- DB: ファイルがない、Tutor DB でない、アプリより新しい schema version。DB は SQLite の読み取り専用モード（`mode=ro`）で開き、schema の作成・upgrade もしない
- allowlist: 未知のキー、0 件・500 件超、`item_id` の重複、DB にない Item、`canonical_form` の不一致
- カードの文字列: 長さの上限超え、改行以外の制御文字、HTML タグらしい記述、URL、メールアドレス、API キーや ID らしい 32 文字以上の英数字列
- 出力先: 既にある（古いファイルと混ざる）、Git 作業ツリーの中（commit に混ざる）

この検査は事故の歯止めで、内容の承認ではない。人名、私的な会話の文、権利の不明な例文、LLM が作った説明の誤りは機械では判定しないので、手順 5 で本人が確かめる。

出力物と allowlist は Git 作業ツリーの外に置き、main / develop へ commit しない。テストと CI は合成データ（一時ディレクトリ）だけを使い、実データの Snapshot を artifact に残さない。#223 の `gh-pages` ブランチは別扱いで、本人が公開を承認した教材と静的画面だけを置く。アプリの履歴と共通の祖先を持たない。allowlist・DB・個人 Snapshot はそこにも置かない。

## ビューアーと後続公開の前提

- #222 静的ビューアー: 同じ配布内の `snapshot.json` だけを取得し、LAN の API、TTS、解析、外部 font に接続しない。答えの開閉はメモリ上の状態だけで、回答の記録や後日の同期はしない。`schema_version` が `public-v1` でない、形が不正、取得に失敗したときは簡潔なエラーにする。`generated_at` を表示し、古い内容を最新と誤認させない。
- #223 公開: 公開する `snapshot.json`（sha256）と公開先を本人が承認してから、ビューアーと `snapshot.json` だけを配布する。アプリ repo は所有者の判断で public にする（2026-11-07、[公開・更新・停止の手順](public-readonly-publishing.md)の手順2）。実教材の Snapshot は main / develop へ commit せず、承認した一般教材だけを `gh-pages` に置く。承認済みの一般教材が Git 履歴にも残ることを本人に説明する。GitHub Pages の通常のサイトは誰でも読める。戻すときは直前に承認した版を配布し直し、誤公開なら配布を止める。外部で保存・cache された内容は回収できない。

## 対象外（必要になってから検討）

private-v1 と本人限定の due / weakness、Cloudflare Access などの本人認証、例文・出典（provenance）の項目、内容 hash の manifest・bundle hash の承認台帳・厳密な byte 再現性、有効期限（`expires_at`）、オフライン PWA。

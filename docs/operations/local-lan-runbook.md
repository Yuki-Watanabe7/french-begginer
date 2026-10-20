# 家庭内本番の起動・復旧手順（設計草案）

この文書は [ADR 0001](../adr/0001-local-lan-and-remote-readonly-hosting.md) の運用手順案。2026-10-20 時点で、本番 Compose、バックアップ用コマンド、自動起動設定は未実装であり、この手順で本番が動作した記録ではない。実装担当は Phase 1/2 で実際のファイル名・コマンド・実測値を確定する。

## 対象と運用開始条件

- 所有者兼復旧担当は Yuki-Watanabe7。Mac ホスト、Windows/Mac ブラウザ、iPhone Safari を初期対象とする。全端末が一人の学習履歴を共有する。
- 所有者が管理する同一 LAN を使用する。ゲスト WiFi と信頼できない端末は分離する。認証なし HTTP の残余リスクを所有者が受け入れない間は localhost だけで動かす。
- ルーターの WAN ポート転送・UPnP 公開・公開トンネルを使わない。IPv6 でも家庭内以外から到達できない設定を確認する。
- SQLite を開発用と別の永続領域へ移し、整合バックアップ、別機器への暗号化コピー、復元訓練が通るまで本番の正本に切り替えない。
- 実機確認は家庭内 LAN で行う。個人データのあるホストで Codespaces のポートを Public にして代替しない。

## 固定する設定（実装時に値を記録）

| 項目 | 設計値・確認方法 |
|---|---|
| Compose | 予定 `compose.production.yml`、専用 project 名 `french-production`。dev ファイルを暗黙に重ねない |
| LAN IP | DHCP 予約した IPv4。実 IP は家庭内の運用記録へ保存し、ここには個人ネットワーク情報を書かない |
| 閲覧 URL | `http://<予約LAN-IP>:8080`。`french-host.local:8080` は任意の補助 |
| 公開ポート | nginx の 8080 のみ。8000 はコンテナ内部、5173 は本番に存在しない |
| フロント設定 | ビルド時 `VITE_API_BASE` は空。端末自身の localhost や Docker サービス名へ fetch しない |
| DB | backend の `TUTOR_DATA_DIR=/var/lib/french-tutor`、DB は同ディレクトリの `tutor.db`（予定） |
| 設定優先順位 | `TUTOR_DATABASE_URL` が存在すると優先される。切替前に競合を検査し、意図しない開発 DB を使わせない |
| 保存領域 | 本番専用 named volume。SQLite の journal/WAL/SHM 用にディレクトリ全体を書込可にする。DB ファイル単独 mount は避ける |
| 所有権 | 非 root backend の UID/GID を固定し、DB ディレクトリはその利用者だけ読書き可。他端末とのファイル共有はしない |
| 秘密 | OpenAI キーは backend の実行時だけ。フロント build 引数、Git、ログ、Snapshot に含めない |
| ホスト保護 | OS ディスク暗号化、ログイン保護、更新。バックアップ復号鍵は同じホストだけに保存しない |

## 起動と日常確認

実装後は専用 Compose を明示指定して起動する。以下は **予定コマンド**で、ファイルがない現状で実行する指示ではない。

```bash
docker compose -f compose.production.yml -p french-production up -d
docker compose -f compose.production.yml -p french-production ps
curl --fail http://<予約LAN-IP>:8080/health
```

nginx の `/health` は backend へ中継する。既存 `/health` はプロセスの応答だけを測るため、DB 書込・migration・バックアップ成功の判定には使わない。実装時には DB readiness を別に検証する方法を追加し、公開応答にパス・個人情報・秘密を載せない。

1. IP・8080 の空きを確認する。競合時は勝手に他プロセスを止めず、このアプリの入口ポートと許可 origin を一緒に変更する。
2. Mac のファイアウォール、Docker/仮想化層のポート公開、ルーターの分離を確認する。Windows ホストを選ぶ場合は Defender Firewall の Private profile・許可 subnet、WSL2 経路を別途検証する。Docker 公開ポートが意図した制限に従うかは別端末で実測する。
3. Mac、Windows、iPhone から `/health` と画面を開く。nginx → `/api` が成功し、ブラウザが 8000 に直接接続していないことを確認する。
4. 本番開始前は合成データで回答を 1 件記録し、別端末の画面で同じ履歴・復習予定に反映することを確認する。日常点検のために余計な学習履歴を作らない。
5. その日の更新後に整合バックアップを作り、暗号化 off-host コピーの成功時刻を確認する。失敗なら復旧可能と表示せず、原因と未保護の期間を記録する。

ホストのスリープ中は LAN 利用もバックアップも停止する。学習時間にだけ起動する運用を許容する。コンテナの再起動設定（例 `unless-stopped`）は Docker 自体を起動しない。Mac ログイン後の Docker 起動、Compose の復帰、DHCP 予約維持を実測する。無人で再起動後すぐ利用する要件が追加されたらホスト選定を見直す。電源断前は更新を止めバックアップ後に停止し、永続 volume を削除する `down -v` は通常停止に使わない。

## SQLite のバックアップ

目標 RPO は稼働日の最終更新から 24 時間以内。予定は日次・学習終了時・upgrade 直前。ホスト停止で予定を逃したら次回起動時に補う。最後の成功した off-host コピーが目標より古ければ未達と記録する。現在、この目標を実現する job はない。

1. 本番 DB を特定し、容量と schema version を確認する。実装するツールは read-only 接続から [SQLite backup API](https://www.sqlite.org/backup.html)（Python `sqlite3.Connection.backup` 等）で新規一時ファイルへコピーする。更新中の DB ファイルを `cp` する方式は採用しない。
2. 完了したコピーに `PRAGMA integrity_check` と `PRAGMA foreign_key_check` を実行する。前者が `ok`、後者が空であること、期待する schema と主要テーブル件数を確認する。失敗した一時ファイルを成功版へ昇格しない。
3. 作成時刻、backup ID、アプリ commit、schema version、サイズ、SHA-256、主要件数を私的 manifest に記録する。文書や CI に実内容を記録しない。整合コピーを確定した後、recipient 公開鍵による暗号化等で保護する（初期候補 `age`）。復号鍵は本人が別に管理する。
4. 暗号化ファイルと manifest を別機器へコピーし、hash と復号・整合性を確認する。初期候補は暗号化済み外付けディスクで、完了後に切り離す。同じ内蔵ディスク、同じ Docker volume、Git、教材の静的ホストは off-host 保存先に数えない。
5. 成功と確認できた最後の版を維持する。保持目安は日次 7、週次 4、月次 3 世代。削除は新しい off-host コピーの確認後。機器未接続なら警告し、RPO 達成と表示しない。公開クラウド保管先の追加は別の配布判断とする。

バックアップ対象は SourceDocument、Candidate、LearningItem と参照、LearningEvent、LearnerState、ReviewSchedule、known 設定とその履歴、schema_migrations を含む **DB 全体**。アプリ版と復旧に必要な非秘密設定も記録する。元音声等の非保存入力を復元できるとは約束しない。API キーは教材・DB バックアップへ足さず、別の秘密管理から再設定する。

## 更新・破損・ホスト故障からの復旧

RTO は動作する代替ホストと復号鍵が揃ってから 4 時間以内が目標。機器調達・鍵紛失にかかる時間は含まれない。達成実績は Phase 2 の復元訓練まで未確認。

1. 書込を停止し、問題の DB と journal/WAL/SHM をまとめて保全する。壊れた DB や現在の volume を上書き・削除しない。
2. 最後に検証済みの off-host 版を空の別ディレクトリへ復号する。hash、integrity、FK、schema、記録した件数を確認する。最新版が不正なら前の正常な世代を選び、失う期間を明示する。
3. バックアップの manifest が指定するアプリ版で隔離した復旧用インスタンスを起動する。実 API キーを渡さず、メール等の外向き処理を発生させない。復旧先の volume 所有権を実行 UID/GID に合わせる。
4. Source、Item、方向別の復習予定、既知指定、最近の履歴を確認する。テスト用コピーで回答保存まで検証し、そのテスト書込を本番復元データに混ぜない。
5. 本番書込停止のまま、検証済みの未変更コピーを新しい本番 volume に配置して起動し、他端末で読取を確認後に書込を再開する。復元した版・失った期間・実測時間を私的運用記録へ残す。
6. 復元後に新しい整合バックアップを作り、個人 Snapshot は新しい `as_of` で別途生成する。外部教材から DB を再構成しない。

upgrade 前には停止中の整合バックアップと復元確認を行う。`schema.py` は起動時に upgrade するため、古いイメージだけへ戻しても旧 schema に戻らない。rollback は旧アプリと upgrade 前バックアップの組合せで行い、upgrade 後の更新消失を報告する。新 schema の DB は保全し、逆 migration を推測で実行しない。

## 実機・障害試験の計画

以下は未実施の受入計画。合成データで実行し、OS/ブラウザ、commit、日時、期待値/実測、成功/失敗を記録する。

| 試験 | 合格条件 |
|---|---|
| Mac Safari/Chrome、Windows Edge、iPhone Safari を同一 WiFi で使用 | 予約 IP から画面・回答記録・履歴共有・再読込が動く。iPhone の入力・音声は LAN 側だけで確認 |
| mDNS を使えない端末 | 予約 IP で接続可。名前の失敗を API 障害と誤診しない |
| ゲスト WiFi・WiFi client isolation | ゲストは拒否。所有端末の WiFi 分離が原因なら必要な LAN 設定だけ是正 |
| 別端末からポート確認 | 8080 だけ許可。8000/5173、許可外 subnet/IPv6、携帯回線からの直接接続を拒否 |
| 別 Origin、未知 Host、有料 TTS GET | 書込・有料処理は他サイト起点を拒否。CORS 削除だけで合格にしない |
| ホスト睡眠・復帰・OS 再起動・Docker 停止 | 停止中は LAN 不可と案内。復帰後に DB が残り、起動手順と所要時間を記録 |
| ポート競合・DB 書込権限不足・容量不足 | 起動失敗を識別し、別の空 DB へ黙って切替しない |
| コンテナ再作成・dev と並行利用 | 本番 DB が残り dev と混在しない。入口ポート競合を検出 |
| 学習更新中の backup・途中失敗・鍵なし | 検証済み世代を保持。不完全版は採用しない。復号不可を成功扱いにしない |
| 別 volume への復元・旧 schema の upgrade | integrity/FK、主要データ、実測 RPO/RTO を確認。元 DB は保全 |
| 家庭 PC 停止中の外出先閲覧 | 最終配布済み教材だけ表示。LAN 本番に接続しない（Phase 5） |

トラブルは「名前解決 → TCP/ファイアウォール → nginx → backend → DB」の順に切り分ける。画面が開くことと、データが保存できること、復旧できることは別々に確認する。

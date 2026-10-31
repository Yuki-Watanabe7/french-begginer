# 家庭内本番の起動・復旧手順

[ADR 0001](../adr/0001-local-lan-and-remote-readonly-hosting.md) の運用手順。

- 2026-10-31 時点で Phase 1（[#219](https://github.com/Yuki-Watanabe7/french-begginer/issues/219)）の本番 Compose・nginx・アクセス境界を実装した。ホスト上の localhost で行った検証は「[検証の記録](#検証の記録)」にある。
- Mac / Windows / iPhone の実機確認、LAN 公開、firewall、ゲスト WiFi、sleep・OS 再起動の確認は所有者がまだ実施していない。
- バックアップ・復元（Phase 2 / [#220](https://github.com/Yuki-Watanabe7/french-begginer/issues/220)）は未実装。復元訓練が通るまで本番は合成データだけで使い、学習の正本（開発用 `backend/data/tutor.db`）を移さない。

## 対象と運用開始条件

- 所有者兼復旧担当は Yuki-Watanabe7。Mac ホスト、Windows/Mac ブラウザ、iPhone Safari を初期対象とする。全端末が一人の学習履歴を共有する。
- 所有者が管理する同一 LAN を使用する。ゲスト WiFi と信頼できない端末は分離する。認証なし HTTP の残余リスクを所有者が受け入れない間は localhost だけで動かす（`FRENCH_BIND_ADDRESS=127.0.0.1`、既定値）。
- ルーターの WAN ポート転送・UPnP 公開・公開トンネルを使わない。IPv6 でも家庭内以外から到達できない設定を確認する。
- SQLite を開発用と別の永続領域へ移し、整合バックアップ、別機器への暗号化コピー、復元訓練が通るまで本番の正本に切り替えない。
- 実機確認は家庭内 LAN で行う。個人データのあるホストで Codespaces のポートを Public にして代替しない。

## 構成と固定値

| 項目 | 値・確認方法 |
|---|---|
| Compose | `compose.production.yml`、project 名 `french-production`。必ず `bash scripts/production_compose.sh <compose の引数>` から操作する。wrapper が `-f` / `-p` / `--env-file` を固定し、dev の `docker-compose.yml` やリポジトリ直下の `.env` を重ねない |
| 設定ファイル | `production.env`（`production.env.example` から作成、Git 管理外）。wrapper はシェルの `OPENAI_API_KEY` / `FRENCH_*` を消してから読むので、開発シェルの値は本番に入らない |
| 入口 | nginx（`nginxinc/nginx-unprivileged`、uid 101）の 8080。ホスト側は `${FRENCH_BIND_ADDRESS}:${FRENCH_HTTP_PORT}`、既定 `127.0.0.1:8080` |
| 閲覧 URL | localhost 運用中は `http://localhost:8080`。LAN 公開後は `http://<予約LAN-IP>:8080`、`french-host.local:8080` は任意の補助 |
| 公開しないポート | backend 8000 はコンテナ間だけ（`expose`）。5173 は本番に存在しない |
| フロント | build 時 `VITE_API_BASE` は空。nginx が `/api/` と `/health` を同一オリジンで backend へ中継し、Host を書き換えない。backend を作り直して IP が変わっても Docker の内部 DNS で引き直す |
| backend | `APP_ENV=production`、uid 10001 の非 root、rootfs 読取専用、`--workers 1`、`--reload` なし、dev 依存なし。書けるのは DB volume、TTS cache volume、`/tmp`（tmpfs）だけ |
| 許可 Host | `FRENCH_ALLOWED_HOSTS`（ポートなし、カンマ区切り）+ 常に `localhost` / `127.0.0.1` / `[::1]`。それ以外は 400 |
| DB | `TUTOR_DATA_DIR=/var/lib/french-tutor`、DB は `tutor.db`。`TUTOR_DATABASE_URL` は空に固定（設定されると優先されるため） |
| DB volume | external named volume `french-production-tutor-data`（ディレクトリ全体、0700、uid 10001）。external なので compose は作らず、`down -v` でも消えない。名前違いで空 DB を黙って作ることもない |
| TTS cache | named volume `french-production-tts-cache`。消えても再生成できる（再生成時に API 費用が発生する） |
| 秘密 | `OPENAI_API_KEY` は `production.env` から backend の実行時だけに渡す。フロント build、Git、ログに入れない。`production_compose.sh config` の出力にはキーが展開されるので貼り付けない |
| イメージ | 各ベースイメージは版と digest で固定する（`backend/Dockerfile`、`frontend/Dockerfile`）。Python 依存は `uv.lock`、Node 依存は `package-lock.json` どおりに入れる |
| ホスト保護 | OS ディスク暗号化、ログイン保護、更新。バックアップ復号鍵は同じホストだけに保存しない |

## 初回セットアップ（localhost だけで動かす）

```bash
cp production.env.example production.env             # 値は既定のまま（127.0.0.1）
docker volume create french-production-tutor-data      # 初回だけ。既にあれば作り直さない
bash scripts/production_compose.sh up -d --build --wait
bash scripts/production_compose.sh ps                  # backend / web が (healthy)
bash scripts/production_compose.sh exec backend python -m app.persistence.readiness
bash scripts/probe_production_boundary.sh 127.0.0.1    # 全項目 PASS
```

初回起動で backend が空の DB を作り、現行 schema を記録する。`ready: ok (... schema_version=5)` を確認する。`external volume "french-production-tutor-data" not found` が出たら、初回なら上の `docker volume create` を実行する。初回でないのに出た場合は volume 名か Docker の接続先が違うので、新しい volume を作らずに `docker volume ls` と `docker context ls` を確認する。

## LAN へ公開する（所有者の判断後）

認証なし HTTP の残余リスク（LAN に届く端末は全機能と API 費用を使え、通信は盗聴・改変されうる）を所有者が受け入れた後に行う。受け入れない場合や、ゲスト・来客・信頼できない IoT を分離できない場合は localhost のままにする。HTTPS と入口認証が必要なら先に別 Issue で設計する。

1. ルーターでホストの DHCP 予約を設定し、Mac で予約 IP を確認する（`ipconfig getifaddr en0`。有線なら該当 interface）。実 IP はこの文書ではなく私的な運用記録に残す。
2. `production.env` を変更する。`FRENCH_BIND_ADDRESS` に予約 IP を1つ書き、`0.0.0.0` にはしない（IPv6 を含む全 interface で待ち受けうる）。`FRENCH_ALLOWED_HOSTS` に端末で開くホスト名を書く（例: 予約 IP と `french-host.local`）。
3. `bash scripts/production_compose.sh up -d --wait` で反映する。`lsof -nP -iTCP:8080 -sTCP:LISTEN` が予約 IP の IPv4 だけを示し、`*:8080` や IPv6 を示さないことを確認する。
4. Mac の firewall を確認する。`/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` で状態を見る。macOS のアプリ firewall は送信元 subnet を絞れない。subnet で絞る場合は pf の anchor で、予約 IP の 8080 を信頼 LAN の CIDR だけに許す。ネットワーク設定の変更は所有者が行い、変更内容を運用記録に残す。
5. ルーターでゲスト WiFi と client isolation の設定を確認する。WAN 側のポート転送・UPnP・DMZ が無効であることも確認する。
6. 別の端末で `bash scripts/probe_production_boundary.sh <予約IP>` を実行する（Mac のターミナル、または Windows の Git Bash / WSL）。iPhone は Safari で画面を開いて確認する（下の実機確認）。
7. IPv6 を確認する。ホストの IPv6 アドレス（`ifconfig en0 | grep inet6`）に別端末から `curl -g -6 --connect-timeout 3 "http://[<IPv6>]:8080/health"` を実行し、接続できないこと。携帯回線（WiFi を切った iPhone）から予約 IP / 公開 IP に接続できないことも確認する。
8. ゲスト WiFi に接続した端末から予約 IP:8080 に接続できないことを確認する。

## 起動と日常確認

```bash
bash scripts/production_compose.sh up -d --wait
bash scripts/production_compose.sh ps
bash scripts/production_compose.sh exec backend python -m app.persistence.readiness
bash scripts/probe_production_boundary.sh <localhost または予約IP>
```

- `ps` の `(healthy)` は、backend が DB を開けて書け（readiness）、`/health` に応答していることを示す。web の healthy は nginx 経由の `/health` が通ることを示す。どちらもバックアップ成功は意味しない。
- `/health` は外向けに `{"status":"ok"}` だけを返す。DB のパスや状態は HTTP に出さず、readiness CLI でだけ見る。
- probe は学習履歴を作らない。動詞の採点 API（状態を持たない）だけを同一オリジンで呼び、TTS は拒否されることだけを確かめる。
- 合成データで回答を1件記録し、別端末の画面で同じ履歴・復習予定が見えることを確認する（本番開始前のみ。日常点検で余計な学習履歴を作らない）。
- curl などブラウザ以外から書込 API を呼ぶ場合は `-H "Origin: http://<host>:<port>"` を付ける。付けないと 403 になる（ブラウザは自動で付ける）。

## 停止・sleep・再起動

- 通常停止は `bash scripts/production_compose.sh stop`、再開は `up -d --wait`。`down` はコンテナを消すが DB volume は残る。`down -v` でも external の DB volume は消えないが、TTS cache は消えるので通常は使わない。
- `restart: unless-stopped` は、プロセスが自分で終了・異常終了したときにコンテナを再起動する。`docker kill` / `docker stop` / `compose stop` は手動停止扱いで、自動では戻らない（2026-10-31 に実測）。手動で止めたら `up -d --wait` で戻す。
- ホストの sleep 中は家庭内学習もバックアップも止まる。復帰後は `ps` で healthy、`ipconfig getifaddr en0` で予約 IP が戻っていることを確かめ、probe を実行する。IP が付く前に Docker が入口を作り直そうとすると失敗するので、そのときは `up -d --wait` をやり直す。
- OS 再起動・ログイン後は、Docker Desktop が起動して初めてコンテナが戻る。Docker Desktop の「Start Docker Desktop when you sign in」設定を確認する（無効なら手動で起動する）。復帰までの所要時間を実機確認の記録に残す。
- 24 時間稼働は約束しない。無人で再起動直後から使える要件が出たら、ホストの選定を見直す。
- 電源を切る前は更新を止め、バックアップしてから停止する（Phase 2 の実装後）。

## 障害の切り分けと回復

「名前解決 → TCP/firewall → nginx → backend → DB」の順に切り分ける。画面が開くこと、データを保存できること、復旧できることは別々に確認する。

| 症状 | 原因と回復 |
|---|---|
| `up` が `ports are not available ... bind: address already in use` で止まり、web が `Created` のまま | 入口ポートを他のプロセスが使っている。`lsof -nP -iTCP:<port> -sTCP:LISTEN` で相手を確認する。他のプロセスを勝手に止めない。必要なら `FRENCH_HTTP_PORT` を変え、端末で開く URL も合わせてから `up -d --wait` |
| `up` が `bind: can't assign requested address` で止まる | `FRENCH_BIND_ADDRESS` の IP がホストに付いていない（DHCP 予約が外れた、sleep 復帰直後など）。`ipconfig getifaddr en0` で確認し、IP か予約を直して `up -d --wait` |
| `external volume "french-production-tutor-data" not found` | 初回なら `docker volume create`。初回でなければ新しい volume を作らない。`docker context ls` で Docker の接続先を、`docker volume ls` で名前を確認する |
| 画面は開くが API が `{"detail":"Host is not allowed"}`（400） | 開いたホスト名が `FRENCH_ALLOWED_HOSTS` に無い。`production.env` に足して `up -d --wait`（backend が作り直される） |
| 書込が `{"detail":"Request origin could not be verified"}` / `Cross-origin request is not allowed`（403） | ブラウザ以外から Origin なしで呼んだ、または別 Origin から呼んだ。正規の画面からの操作で出るなら backend のログ（`logs backend`）の `request rejected` 行を確認する |
| 読み上げが 403 | 画面以外から TTS を呼んだ（`<audio src>`、アドレスバー直打ち等）。仕様どおり。画面の再生ボタンからは独自ヘッダー付きで呼ぶ |
| nginx が 502 | backend が停止・起動中。`ps` と `logs backend` を見る |
| backend が `(unhealthy)`、readiness が `DB の場所にアクセスできない` / `DB に書き込めない` | volume の所有者・権限が実行ユーザー（uid 10001）と違う。下の chown で戻す。別の空 DB に切り替えて回避しない |
| readiness が `schema version ... がコードの版と異なる` / backend が起動しない（`SchemaVersionError`） | DB がコードより新しい（古いイメージに戻した）か、upgrade 途中で止まった。逆 migration を推測で実行しない。下の「更新・破損・ホスト故障からの復旧」に従う |
| readiness が `DB ファイルがない（未初期化）` | backend が起動前、または volume が空。`logs backend` を確認する。初回でないなら volume の取り違えを疑う |

DB volume の所有者を戻す（コンテナを止めずに実行できる）:

```bash
docker run --rm --user 0 --entrypoint chown \
  -v french-production-tutor-data:/var/lib/french-tutor \
  french-production-backend:local -R 10001:10001 /var/lib/french-tutor
bash scripts/production_compose.sh exec backend python -m app.persistence.readiness
```

## イメージと依存の更新

固定した版は自動で上がらない。更新はこの手順でまとめて行い、PR で差分を確認する。

1. ベースイメージの新しい版を選び、digest を取得する（`docker buildx imagetools inspect <image>:<tag>`）。公開から 2 週間以上経った版を選ぶ。`backend/Dockerfile` と `frontend/Dockerfile` の `<tag>@sha256:<digest>` を更新する。
2. Python 依存は `cd backend && uv lock --upgrade-package <name>`、Node 依存は `cd frontend && npm install <name>@<version>` で lock ファイルを更新する。
3. `bash scripts/quality-check.sh` を通す。
4. `bash scripts/production_compose.sh build` の後、`docker scout cves local://french-production-backend:local --only-severity critical,high`（web も同様）で既知の脆弱性を確認する。
5. Phase 2 の実装後は upgrade 前に整合バックアップを取る。それまでは合成データだけで行う。
6. `up -d --wait`、readiness、probe を実行し、画面で回答を1件確認する。

2026-10-31 の scan では、`uv.lock` の anyio / certifi / pypdf / starlette と、Debian / Alpine のベースイメージの一部パッケージに critical・high の既知脆弱性があった（開発環境も同じ版を使う）。web イメージでは使わない curl を削除した。本番開始前に [#226](https://github.com/Yuki-Watanabe7/french-begginer/issues/226) で依存を更新し、scan をやり直す。

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

## 検証の記録

### ホスト上の localhost での検証（2026-10-31、#219 の実装ブランチ）

環境: macOS 26.5.2（arm64）、Docker Desktop（Engine 29.9.2、Compose v5.6.1）。`FRENCH_BIND_ADDRESS=127.0.0.1`、合成データだけ。LAN への公開は行っていない。

| 試験 | 実測 |
|---|---|
| build・起動 | backend / web とも約 13 秒で healthy。ホストで待ち受けるのは `127.0.0.1:8080`（IPv4）だけ |
| `probe_production_boundary.sh 127.0.0.1` | 12 項目すべて PASS（nginx 経由の `/health`、React、直接 URL の再読込、同一オリジンの書込、8000 / 5173 に接続不可、未知 Host 400、別 Origin・Origin なしの書込 403、独自ヘッダーなし・別 Origin の TTS 403、preflight に CORS 許可なし） |
| 実行ユーザー・書込先 | backend uid 10001、web uid 101。rootfs への書込は `Read-only file system`、`/tmp` は書込可。DB ディレクトリは 0700・uid 10001。pytest / ruff / uv はイメージに無い。開発 DB はイメージに入っていない |
| 設定の分離 | シェルに `OPENAI_API_KEY` と `FRENCH_BIND_ADDRESS=0.0.0.0` があっても、展開結果は `production.env` の値（キー空、127.0.0.1）だった |
| DB volume が無い | `up` が `external volume ... not found` で止まり、コンテナも空 DB も作られない |
| 永続性 | 合成 Source 1件が `restart`、`down` → `up`（コンテナ再作成）、`down -v` の後も残る。`down -v` で消えたのは TTS cache だけ |
| プロセスの異常終了 | backend の PID 1 を内部から終了させると自動再起動（RestartCount 0→1）し、healthy に戻る。`docker kill` 後は自動で戻らず `up -d` が必要 |
| backend だけ作り直して IP が変わる | 修正前は nginx が古い IP に中継して 502。内部 DNS で引き直す設定にした後は 200 |
| DB 権限不足 | DB ディレクトリを root 所有にすると readiness が原因付きで exit 1、書込 API は 500、約 90 秒で `(unhealthy)`。chown で戻すと healthy |
| ポート衝突・IP 未割当 | それぞれ `address already in use` / `can't assign requested address` で `up` が exit 1。原因を除いて `up -d --wait` で戻る |
| 大きなアップロード | 30 MB の multipart は nginx が 413（上限 26 MB、音声取り込み上限 25 MB） |
| TTS の正規経路 | 同一オリジン + 独自ヘッダーは guard を通る（キー未設定のため 503、API 呼び出しなし） |
| cache | `/assets/*` は `immutable`、`index.html` などは `no-cache` |

自動テスト: `test_request_guard.py`、`test_runtime_settings.py`、`test_database_readiness.py`、`test_production_config.py`、`test_tts.py::test_tts_cache_dir_from_env`、`useTTS.test.ts`。

### 所有者による実機確認（未実施）

合成データで行い、日時、commit、ホストの OS・Docker の版、端末の OS・ブラウザ、期待値、実測、成否を私的な運用記録に残す。実 IP や SSID はこの文書に書かない。

| 試験 | 合格条件 |
|---|---|
| Mac Safari / Chrome、Windows Edge、iPhone Safari を同一 WiFi で使用 | 予約 IP から画面表示・回答記録・別端末での履歴共有・再読込が動く。iPhone の入力・音声は LAN 内だけで確認 |
| mDNS を使えない端末 | 予約 IP で接続できる。名前の失敗を API 障害と誤診しない |
| 別端末から `probe_production_boundary.sh <予約IP>` | すべて PASS（8000 / 5173 に接続できない、未知 Host・別 Origin・TTS の拒否） |
| 許可外 subnet・IPv6・携帯回線 | いずれからも接続できない |
| ゲスト WiFi・client isolation | ゲストからは拒否。所有端末同士が WiFi 分離で繋がらないなら必要な LAN 設定だけ直す |
| ホストの sleep・復帰、OS 再起動、Docker Desktop 再起動 | 停止中は LAN から使えない。復帰後に DB が残り、healthy に戻る。手順と所要時間を記録 |
| dev と並行利用 | dev（5173 / 8000）と本番（8080）が同時に動き、DB が混ざらない |

### Phase 2 以降の試験計画（未実施）

| 試験 | 合格条件 |
|---|---|
| 学習更新中の backup・途中失敗・鍵なし | 検証済み世代を保持。不完全版は採用しない。復号不可を成功扱いにしない |
| 別 volume への復元・旧 schema の upgrade | integrity/FK、主要データ、実測 RPO/RTO を確認。元 DB は保全 |
| 容量不足 | 起動失敗・書込失敗を識別し、別の空 DB へ黙って切り替えない |
| 家庭 PC 停止中の外出先閲覧 | 最終配布済み教材だけ表示。LAN 本番に接続しない（Phase 5） |

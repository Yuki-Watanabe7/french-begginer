# SQLite の暗号化バックアップと復元（Issue #220）

学習履歴を失わないための実行手順。家庭内本番の起動条件は [local-lan-runbook](local-lan-runbook.md)、設計は [ADR 0001](../adr/0001-local-lan-and-remote-readonly-hosting.md) にある。

この実装は本番 DB の正本切替、外部機器の選定、私的データの転送、自動実行の登録を行わない。下記の合成データ検証と、所有者の別機器・復号鍵による受入を分ける。後者が済むまで正本を切り替えない。

## 本番 DB の場所と初回作成

コンテナ内の保存先は `/var/lib/french-tutor/tutor.db`、実行 UID/GID は `10001:10001`、ディレクトリは `0700`。開発の `backend/data/tutor.db` と共有しない。`APP_ENV=production` で `TUTOR_DATABASE_URL` が非空、保存ディレクトリが別、所有権・journal 作成権限が不適切、DB 不在・未初期化なら通常起動を拒否する。確認後のファイル消失も `mode=rw` 接続で拒否する。

**初回の空 volume だけ**、次を実行する。既存の DB は空ファイルでも上書きしない。以前から存在する環境で DB が無い場合は初期化せず、Docker の接続先・volume 名を確認し、復元する。

```bash
cp production.env.example production.env
docker volume create french-production-tutor-data
bash scripts/production_compose.sh build
bash scripts/production_compose.sh run --rm --no-deps backend \
  python -m app.persistence.production initialize-empty-volume
bash scripts/production_compose.sh up -d --wait
bash scripts/production_compose.sh exec -T backend python -m app.persistence.readiness
```

既に schema 付き DB がある場合は初期化コマンドを実行しない。DB ディレクトリの所有権修復は [既存手順](local-lan-runbook.md#障害の切り分けと回復) に従う。コンテナを作り直しても external volume は残る。

## 保存先と鍵を準備する

ホストに `uv`、Docker CLI、[age / age-keygen](https://github.com/FiloSottile/age#installation) が必要。`age --version` / `age-keygen --version` を確認する。macOS の一例は `brew install age`。本番コンテナへ復号鍵や age を入れる必要はない。

1. 所有者が暗号化した**物理的に別の機器**を選び、実際の backing device を OS のディスク管理で確認する。別 APFS volume や別パーティションだけでは別機器ではない。スクリプトは mountpoint、異なる filesystem、下記 ID を検査するが、物理ディスクの独立性までは証明しない。新しいクラウド保存先を追加しない。
2. 別管理する機器上で `age-keygen -o /PRIVATE/identity.key` を実行し、`age-keygen -y /PRIVATE/identity.key > /PRIVATE/recipients.txt` で公開鍵だけのファイルを作る。日次バックアップ用ホストへコピーするのは `recipients.txt` だけ。秘密鍵をリポジトリ、バックアップデータ機器、CI、教材サイトに保存しない。別保管の復号鍵を復元時に利用できるか確認する。
3. 接続済み外付け機器のルートに `uuidgen > /Volumes/FrenchTutorBackup/.french-tutor-backup-device` で ID を付ける。これは保存先を所有者が特定した記録で、暗号化や認証の代わりではない。
4. `scripts/backup.config.example.json` をリポジトリ外の私的ディレクトリへコピーし、`local_dir`、`offhost_mount`、`device_id`、`recipients_file` を実際の値にする。`device_id` は手順3の内容。設定 JSON は `0600`、`local_dir` は `0700` にする。`local_dir` はホスト側、機器は別 filesystem が必要。DB・鍵・設定・世代・復元先をリポジトリ内に指定すると拒否する。

以後の例では、私的設定の場所をシェルに明示する。実際のパス・鍵・manifest を GitHub へ貼らない。

```bash
export FRENCH_BACKUP_CONFIG=/PRIVATE/backup.config.json
uv sync --project backend --locked --group dev
uv run --project backend --no-sync python scripts/production_backup.py backup \
  --config "$FRENCH_BACKUP_CONFIG" --reason daily
uv run --project backend --no-sync python scripts/production_backup.py status \
  --config "$FRENCH_BACKUP_CONFIG"
```

バックアップは現在の本番コンテナの image ID と専用 volume を特定する。一時コンテナは非 root、ネットワークなし、既存コンテナの volume を読取専用で継承し、API キーを渡さない。`--volumes-from` を使うため、元コンテナを見失った際に別の空 volume を作らない。先に `down` で元コンテナを消さない。

イメージには build 時の Git commit と未コミット変更の有無を記録する。復旧は manifest の commit に加え、receipt の正確な image ID を使う。`app_dirty=true` は Git commit だけでは再現できない build であり、本番切替には使用しない。初めてこの機能を導入するときは、合成データの環境でこの版のイメージへ更新してから検証する。バックアップ機能のない旧イメージで `export` は実行できない。

## 成功と未達の意味

[SQLite backup API](https://www.sqlite.org/backup.html)（[Python 3.12 の Connection.backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)）を読取接続から使う。書込中のファイルを `cp` しない。ロック・更新が続いた場合も時間制限を設け、失敗した一時コピーを採用しない。

コピー後に integrity、FK、schema version・列・主キー・FK 定義、全主要テーブル件数、方向別 Schedule 件数を確認する。Source、Candidate、Item と source_refs、Event、State、方向別 Schedule、known 現在値・履歴、schema_migrations を含む DB 全体が対象。元音声等の非保存入力や API キーは追加しない。

DB と私的 manifest（commit、schema、時刻、サイズ、件数、SHA-256、非秘密の実行条件）をまとめて [age の公開鍵暗号化](https://github.com/FiloSottile/age#usage) する。暗号化前のコピーは `0700` の一時ディレクトリだけに置き、処理終了時に消す。ホストの強制終了で残った `.pending-*` には平文がありうるため、ホストのディスク暗号化を維持し、再起動後に残存を確認する。残存物を成功版へ手動昇格しない。

暗号化済み世代は `<backup ID>/archive.age` と `receipt.json` の2ファイル。別機器の一時ディレクトリへ書き、flush/fsync、暗号文ハッシュ一致、機器 ID 再確認後に世代名へ rename する。receipt に実内容や件数は出さないが、commit・schema・時刻は私的情報として扱う。

| 表示される項目 | 意味 |
|---|---|
| `encrypted-offhost-copy-verified` | 暗号化と指定機器へのコピー・hash 照合済み。復号・アプリ復旧の確認ではない |
| `failed` / `未達` / 終了コード1 | その試行は未達。前の `last_success` は保持。不完全な一時世代は採用しない |
| `not-due` | 現在も接続・hash 確認できる前回コピーが20時間以内なので日次を省略 |
| `rpo_met` | 接続・hash 確認できる最後のコピーの取得開始から24時間以内。取得開始を使う保守的な判定 |
| `restore_verified: false` | 日次処理は復号鍵を持たず、復元可能性を推測しない。下記の復元記録で確認する |

`status` は読み取りのみ。未接続、hash 不一致、前回コピーなし、24時間超なら `rpo_met=false`、終了コード1。未接続中に前回成功時刻が表示されても、現在の確認に成功したとは扱わない。

世代保持は、新しい別機器コピーの検証後だけ行う。直近7日分・4週分・3月分の各最新世代の和集合を残す。同一日の追加版を全て7世代と数える方式ではない。upgrade 前の世代は自動削除しない。壊れた世代が見つかったら削除を止める。別機器へ届かなかったローカル暗号化世代と中断時の一時物は自動削除の対象外。検証済み世代と復元記録を確認して所有者が整理する。

## 日次・学習終了・更新

日次処理の雛形は `scripts/com.french-tutor.backup.plist.example`（macOS launchd）。絶対パス、設定・ログの私的保存先を実値に直し、全体を `0600` で `~/Library/LaunchAgents/com.french-tutor.backup.plist` へ配置して、所有者が登録する。この作業では登録しない。

```bash
plutil -lint "$HOME/Library/LaunchAgents/com.french-tutor.backup.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.french-tutor.backup.plist"
launchctl print "gui/$(id -u)/com.french-tutor.backup"
```

ログイン時と1時間ごとに `--reason daily --if-due` を試し、20時間を過ぎた成功版を更新する。ホスト sleep、Docker 停止、機器未接続は成功扱いにせず、次の実行で補う。登録しただけで日次成功とはしない。ログと `status` を確認する。現行のホスト CLI は macOS/Linux の POSIX ロックと権限を使う。Windows はブラウザ利用端末としての対象であり、Windows ネイティブホストの自動実行は未対応。

通常操作は次を使う。

```bash
bash scripts/production_manage.sh start    # 古ければ backup を試し、その後起動
bash scripts/production_manage.sh stop     # web/backend 停止→終了時 backup
bash scripts/production_manage.sh upgrade  # 停止→upgrade前 backup→build・起動・readiness
```

`start` の backup 失敗は警告を出して学習再開を許可する。`stop` / `upgrade` は書込を止めてからコピーし、失敗時は停止を維持する。`upgrade` はバックアップ未達なら build へ進まない。再開を決める場合は失敗原因を確認して `start`。直接の `production_compose.sh stop/up --build` や OS 強制停止はこの処理を迂回するため日常操作に使わない。

`pre-upgrade` では旧 backend image を `french-production-backend:rollback-<image IDの先頭12桁>` にも固定する。稼働中の旧 web image ID も更新前に私的記録へ保存し、必要ならローカルタグを付ける。復旧に使うイメージを `docker image prune -a` で消さない。代替ホストで使えるイメージの保管・再build手順も復元訓練で確かめる。

## 別の領域へ復元して回答保存を確認する

最初に、動くホストと別保管の復号鍵が揃った時刻を記録する。これが RTO（利用再開までの時間）の計測開始。障害時刻を `--recovery-point` に指定し、省略時は復元開始時刻から RPO（失う可能性のある更新の長さ）を保守的に計算する。日時には `+09:00` 等の timezone を付ける。

```bash
uv run --project backend --no-sync python scripts/production_backup.py restore \
  --bundle /Volumes/FrenchTutorBackup/french-tutor-backups/BACKUP_ID \
  --identity /SEPARATE/identity.key \
  --destination /PRIVATE/restore-BACKUP_ID \
  --recovery-point '2026-11-01T10:00:00+09:00' \
  --recovery-started-at '2026-11-01T10:05:00+09:00'

uv run --project backend --no-sync python scripts/production_backup.py verify-application \
  --restored /PRIVATE/restore-BACKUP_ID
```

`restore` は既存ディレクトリを上書きせず、hash・復号・manifest・DB 整合性・schema・件数を照合する。固定2ファイル以外、symlink、パス逸脱を含む tar は拒否する。復号失敗時は復元先を確定しない。`restore-record.json` に版、復旧点、コピー復元時間を保存する。この時点では `rto_met=false`。

`verify-application` は復元DBから**さらに使い捨てコピー**を作り、現行コードの起動時 migration、Source/Item と State/Schedule/known の読取、実際の回答 API による Event 1件追加を検証する。HTTP サーバーや外向き socket、LLM/TTS は使わない。試験書込はこの使い捨てコピーだけ。復元元の DB hash が不変なことを再確認する。回答可能な active Item が無ければ未確認として止める。API テストには dev group が必要。

成功時は同じ私的復元記録に `application_answer_verified=true`、実測 `recovery_seconds`、4時間以内かを示す `rto_met` を追加する。24時間を超えた RPO や4時間を超えた RTO を成功表示へ丸めない。これは記録したホスト・鍵・バックアップの試験結果であり、将来の障害全般を保証しない。

## 別 volume で起動し、正本を切り替える

以下は**復元訓練または所有者が切替を判断した後**に実行する。現在の volume は削除せず保全する。現 DB の保全用ファイルコピーが必要なら、全 writer 停止後に DB と journal/WAL/SHM をまとめて保全する。稼働中バックアップの代替にしない。

新規の復旧専用 volume を作り、未変更の復元 DB を UID/GID 10001 で配置する。`IMAGE_ID` は receipt の image ID。秘密鍵・manifest はコンテナへ渡さない。

```bash
docker volume create french-production-tutor-data-restored-DRILL_ID
docker run --rm -i --network none --read-only --user 10001:10001 \
  --mount type=volume,src=french-production-tutor-data-restored-DRILL_ID,dst=/var/lib/french-tutor \
  --entrypoint python IMAGE_ID -c \
  'import os,sys; p="/var/lib/french-tutor/tutor.db"; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); s=os.fdopen(f,"wb"); s.write(sys.stdin.buffer.read()); s.close()' \
  < /PRIVATE/restore-BACKUP_ID/tutor.db
```

元 volume と同時に mount しない。訓練ではポート公開なしの隔離コンテナで起動・読取・回答を確認し、回答した volume を正本にしない。本番切替は別途未変更の復元コピーを配置した volume で行う。

実際の切替では書込停止のまま `production.env` の `FRENCH_TUTOR_VOLUME` を検証済みの `french-production-tutor-data-restored-<ID>` に変更する。既定は `french-production-tutor-data`、開発シェルの同名変数は wrapper が除去する。external volume が無い、または DB が無い場合は起動に失敗し、空 DB を作らない。現在の正本 volume 名・変更前後の image ID・失う期間を私的記録へ残す。

manifest の旧アプリと upgrade 前 DB の組で戻す場合、古いアプリだけを新 DB に向けない。起動時 upgrade はトランザクション内で行い、DDL 途中失敗も rollback する。逆 migration は行わない。新 DB は元 volume に保全する。旧 backend image ID と旧 web image ID を指定する**私的な Compose override**を用意する。

```yaml
# /PRIVATE/rollback.compose.yml（buildは実行しない）
services:
  backend:
    image: french-production-backend:rollback-IMAGE_PREFIX
  web:
    image: french-production-web:rollback-IMAGE_PREFIX
```

```bash
bash scripts/production_compose.sh -f /PRIVATE/rollback.compose.yml up -d --no-build --wait
bash scripts/production_compose.sh exec -T backend python -m app.persistence.readiness
bash scripts/probe_production_boundary.sh 127.0.0.1
```

同じ override を日常の再起動でも使う運用を確定するまで、通常の `upgrade` は実行しない。通常の設定へ戻す際は、再び停止中 backup を取り、新しいアプリでその復元 DB を upgrade する。切替直後は他端末から読取を確認し、その後に書込を再開する。新しい整合 backup を作り、RPO/RTO と失った期間を記録する。

## 検証と残る受入

自動テスト `backend/tests/test_tutor_backup.py` / `test_production_database.py` は合成データのみ。age / age-keygen が無いローカルでは暗号化関連試験は skip されるため、skip を実測完了と数えない。CI は age をインストールして実行する。

| 検証 | 結果の記録先 |
|---|---|
| 書込中・WAL・未commit・排他ロック・破損・FK/列不足・暗号化失敗・コピー失敗 | 自動テスト。部分世代を成功扱いにしない |
| Source/Candidate/Item/Event/State/方向別Schedule/known/schema の復元と回答保存 | 自動テスト。復元元・稼働DBは不変 |
| schema v4→v5、旧 schema への復帰、新 DB を旧コードが拒否、DDL途中失敗 | 自動テストと合成DBの実行記録 |
| 別の物理機器から別 volume へ復元、別保管鍵での復号、代替ホストのアプリ起動 | **所有者による確認が必要。未実施を達成扱いにしない** |
| 日次登録後の稼働日24h以内、学習終了・upgrade前、sleep復帰・機器未接続 | **実運用の連続記録が必要** |

本番受入の実際のDB・鍵・本文・manifest・運用ログを Git/CI/教材サイトへ送らない。Issue #220 は必要なレビュー・マージと上記の受入を確認するまで閉じない。

### 2026-11-01 の合成データによる実行記録

macOS arm64、Docker Engine 29.9.2、Python 3.12、age 1.3.2。作業時の基点は `2b6f8e1`、未コミット実装を含む専用イメージ `french-issue220-backend:test` で確認した。本番コンテナ・本番 volume・開発 DB は変更していない。

| 試験 | 実測 |
|---|---|
| 通常起動時に DB がない | 初期化せず失敗。明示初期化後は起動可 |
| 専用 volume でコンテナを削除・再作成 | Source/Candidate/Item/Event/State/両方向Schedule/known/schema の件数が残存 |
| 読取専用 volume の一時コンテナから export → age 暗号化 → 復号 | 全主要件数・schema・DB hash を検証。保存機器は**同一ホスト上の模擬ディレクトリ**であり、物理的な off-host 達成ではない |
| 復元元のさらにコピーでアプリ検証 | 復旧点から約0.24秒、復元開始から回答保存検証まで約0.72秒。ホスト・鍵・コードが準備済みの合成試験のみ。実運用の RPO/RTO 達成記録ではない |
| 復元 DB を別の新規 Docker volume に配置・実アプリ起動 | ポート公開・外部ネットワークなしで回答 API が201、Event が1件増加。元の稼働DBと未変更の復元ファイルは hash 不変 |
| 実際の旧アプリで v4 を作成し現行コードで v5 へ更新 | 旧 commit `62434f74f3ba6f4c0e407cf42489f22fd004449d` を Git 履歴から読み出して別プロセスで実行。旧アプリは保全したv4を読め、v5を `SchemaVersionError` で拒否。旧DBは不変 |
| 後片付け | この試験で作成した `french-issue220-*` のコンテナ・volume を削除。検証用イメージ以外の本番資源は変更なし |

自動実行の登録、実際の別物理機器、所有者の別保管鍵、代替ホストへの移行は未実施。

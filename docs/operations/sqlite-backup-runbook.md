# SQLite の保存先とバックアップ（Issue #220）

家庭内本番の学習履歴を、コンテナの作り直しで失わず、必要なときに手元で1コマンドでバックアップ・復元するための手順。起動・LAN 公開は [local-lan-runbook](local-lan-runbook.md) にある。

## 方針と割り切り

個人利用のため、大がかりな災害復旧よりも日常の使いやすさと手軽なバックアップを優先する（[#209](https://github.com/Yuki-Watanabe7/french-begginer/issues/209) / [#220](https://github.com/Yuki-Watanabe7/french-begginer/issues/220)、2026-11-01 改訂）。

| 備えるもの | 方法 |
|---|---|
| コンテナの再作成・アプリの再起動・`down` | 本番専用の external volume に DB を置く。開発 DB とは別 |
| 保存先の取り違え | 通常起動は DB を作らない。volume や DB が無ければ起動に失敗する |
| 操作ミス・アプリ更新の失敗・DB の破損 | 手動のバックアップ（下記）から戻す |

備えないもの（必要になったら後から足す）:

- **最後のバックアップより後の学習履歴**。DB が壊れたら、その間の更新は失われる。
- **PC 自体の故障・紛失**。既定の保存先は同じ PC。備えるならバックアップのファイルを外付けディスク等へ自分でコピーする（任意）。
- 自動・定期のバックアップ、暗号化、別機器への自動コピー、世代管理、復元演習、RPO / RTO の目標と計測。
- 取り込み時に保存しない元の音声・PDF など。API キーは DB に入らないので `production.env` 側で管理する。

## 保存先

| | 本番 | 開発 |
|---|---|---|
| DB | external volume `french-production-tutor-data` の `/var/lib/french-tutor/tutor.db` | `backend/data/tutor.db` |
| 操作 | `bash scripts/production_compose.sh ...` | `docker compose up` / `uv run uvicorn ...` |

- volume は external なので Compose が作らず、`down` / `down -v` でも消えない。開発の bind mount・リポジトリとは共有しない。
- `APP_ENV=production` では、`TUTOR_DATABASE_URL` が空でない、`TUTOR_DATA_DIR` が固定値と違う、DB が無い・未初期化、所有者や権限が違う場合に起動しない。空の DB を作って先へ進むことはない。
- 初回だけ空の volume を明示的に初期化する（[初回セットアップ](local-lan-runbook.md#初回セットアップlocalhost-だけで動かす)）。既存の環境で「DB がない」と言われたら初期化せず、`docker volume ls` と `docker context ls` で volume 名と Docker の接続先を確かめ、必要ならバックアップから復元する。

## バックアップを取る

```bash
bash scripts/production_backup.sh
# 保存しました: /Users/<you>/FrenchTutorBackups/tutor-20261103T120000Z.db
```

- backend は止めなくてよい。SQLite の backup API で、書込中でも整合したコピーを取る（使用中の DB ファイルを `cp` しない）。
- コピーは integrity・外部キー・schema version を確かめてから保存し、受け取ったファイルも開き直して検査する。失敗したら作りかけを残さず終了コード 1 で終わる。
- 保存先の既定は `~/FrenchTutorBackups`（ディレクトリ `0700`、ファイル `0600`）。`FRENCH_BACKUP_DIR=/path bash scripts/production_backup.sh` で変えられる。リポジトリ内は拒否する。
- 中身は**暗号化していない** SQLite で、教材本文と学習履歴を含む。Git・公開教材・CI artifact・Issue やチャットに置かない。ホストのディスク暗号化（FileVault 等）は有効にしておく。
- 取るタイミングの目安は、アプリ更新の前、まとまった学習の後、気になったとき。自動実行は登録しない（欲しくなったら cron / launchd で各自登録してよい）。
- 古いファイルは自動で消さない。容量が気になったら手で消す。

## 復元する

```bash
bash scripts/production_restore.sh ~/FrenchTutorBackups/tutor-20261103T120000Z.db
```

1. web / backend を停止して書込を止める。
2. ファイルを volume へ送り、integrity・外部キー・schema version を検査する。不正なら DB は変えず、停止したまま終わる。元の DB で再開するなら `bash scripts/production_compose.sh up -d --wait`。
3. 現在の DB を消さずに `tutor-before-restore-<時刻>.db` へ改名し、検査済みのファイルを `tutor.db` にする。
4. 起動して readiness を確かめる。バックアップの schema が古ければ、起動時に現行版へ更新される。アプリより新しい schema のバックアップは拒否する。

復元後は画面で直近の学習履歴を確かめる。バックアップより後の更新は戻らない。

差し替え前の DB に戻したいときは、volume から取り出して同じ手順で復元する。`<時刻>` は復元時に表示された名前を使う。

```bash
bash scripts/production_compose.sh run --rm --no-deps -T backend ls /var/lib/french-tutor
bash scripts/production_compose.sh run --rm --no-deps -T backend \
  cat /var/lib/french-tutor/tutor-before-restore-<時刻>.db > ~/FrenchTutorBackups/before-restore.db
bash scripts/production_restore.sh ~/FrenchTutorBackups/before-restore.db
```

不要になった `tutor-before-restore-*.db` は `bash scripts/production_compose.sh run --rm --no-deps -T backend rm /var/lib/french-tutor/tutor-before-restore-<時刻>.db` で消す。

## 開発 DB の学習履歴を本番へ移す（所有者が決めたときだけ）

これまで開発用 `backend/data/tutor.db` に記録した学習を本番で続けるときも、同じ仕組みで移せる。本番 DB の内容は置き換わる（元は `tutor-before-restore-*.db` に残る）。移した後は開発側で学習を続けない。

```bash
(cd backend && uv run python -m app.persistence.backup export) > ~/FrenchTutorBackups/dev-tutor.db
bash scripts/production_restore.sh ~/FrenchTutorBackups/dev-tutor.db
```

## 検証

自動テスト（合成データのみ、Docker 不要）:

- `backend/tests/test_tutor_backup.py`: 全学習テーブルの複製、WAL・未 commit・書込中・ロック時の整合、破損・参照切れ・新しすぎる schema の拒否、復元時の旧 DB と journal / WAL の退避、不正なファイルで DB を変えないこと、旧 schema の起動時 upgrade
- `backend/tests/test_production_backup_scripts.py`: 2つのスクリプトの操作順、保存先の権限、リポジトリ内の拒否、失敗時に作りかけを残さないこと・停止を維持すること
- `backend/tests/test_production_database.py`: 本番で DB を黙って作らないこと

### 2026-11-03 の Docker での確認

macOS arm64、Docker Engine 29.9.2。稼働中の本番 `french-production` には触れず、名前だけを変えた使い捨ての Compose project・volume・image で、合成データだけを使った。確認後に削除した。

| 確認 | 結果 |
|---|---|
| 空の volume で通常起動の DB 接続 | 失敗し、volume に DB を作らない |
| 明示初期化 → `up -d --wait` | healthy、readiness ok |
| 起動中に `production_backup.sh` | 約 2 秒。`0600` のファイル 1 つ、Docker の進捗表示は混入せず SQLite として ok |
| バックアップ後に回答 1 件 → `production_restore.sh` | 回答数がバックアップ時点（3 → 2）に戻り、readiness ok。旧 DB は `tutor-before-restore-*.db` に残る |
| `down` → `up`（コンテナ再作成） | 学習履歴が残る |
| 差し替え前の DB を取り出して復元 | 回答数が 3 に戻る |
| 壊れたファイルで復元 | `restore 失敗` で停止したまま。DB は変わらず、`up -d --wait` で元の状態に戻る |
| 合成の開発 DB を `export` → 本番へ復元 | Source 3 件が本番の画面 API に出る |

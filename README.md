# French Beginner — フランス語動詞活用練習アプリ

フランス語の動詞活用を反復練習で身につけるスマホ対応Webアプリです。

## 技術スタック

| 項目 | 技術 |
|------|------|
| Frontend | React 18 + TypeScript + Vite |
| Backend | Python 3.12 + FastAPI |
| Package管理 (FE) | npm |
| Package管理 (BE) | uv |
| 開発環境 | Docker Compose / Dev Container / GitHub Codespaces |
| DB (初期) | SQLite（Tutor学習データ） / 動詞・名詞はコード内辞書 |
| CI | GitHub Actions |

---

## ローカル起動方法

### Docker Compose（推奨）

前提条件: Docker / Docker Compose がインストールされていること

```bash
docker compose up
```

### Backend 個別起動

前提条件: Python 3.12 以上、[uv](https://docs.astral.sh/uv/) がインストールされていること

```bash
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend 個別起動

前提条件: Node.js 22 以上がインストールされていること

```bash
cd frontend
npm install
npm run dev
```

> **注意**: Vite の開発サーバーは `/api` リクエストを `http://backend:8000`（Docker サービス名）にプロキシします。Docker を使わずに Frontend を単独起動する場合は、別途 Backend が `localhost:8000` で起動していること、または `VITE_API_BASE=http://localhost:8000 npm run dev` のように環境変数で指定してください。

### URL / ポート

| 項目 | URL |
|------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| FastAPI ドキュメント | http://localhost:8000/docs |
| Vite プロキシ（Docker内） | `/api` → `http://backend:8000` |

### 停止

```bash
docker compose down
```

---

## GitHub Codespaces での起動方法

### アプリ起動

1. GitHub リポジトリページで **Code → Codespaces → Create codespace on main** をクリック
2. Codespaces が起動したら、ターミナルで:
   ```bash
   docker compose up
   ```
3. 「ポート」タブに `5173`（Frontend）と `8000`（Backend）が表示されることを確認

### スマホでの動作確認

4. 「ポート」タブで `5173` の行を右クリックし、**Visibility → Public** に変更
5. `5173` の転送先 URL（`https://<codespace-name>-5173.app.github.dev` 形式）をコピー
6. スマホブラウザでそのURLを開く
7. 以下の学習ループが動作することを確認:
   - 問題（動詞・時制・主語）が表示される
   - 活用形を入力して「確認」を送信できる
   - 正誤フィードバックが表示される
   - 次の問題に進める

---

## TTS（音声読み上げ）機能

フランス語テキストを OpenAI TTS API で音声化する機能が利用可能。

- **`OPENAI_API_KEY` の設定が必要なのは TTS機能を使う場合のみ**
- 動詞活用・名詞クイズなどの基本機能は APIキーなしで利用可能
- APIキー未設定時、`/api/tts/speak` は 503 を返す（他の機能への影響なし）

設定方法や CI での取り扱い方針は [docs/tts_verification.md](docs/tts_verification.md) を参照。

---

## API 概要

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| GET | `/api/questions/next` | 次の問題を取得 |
| POST | `/api/answers/check` | 回答を送信して正誤判定 |
| GET | `/api/tts/speak` | フランス語テキストを音声化（`OPENAI_API_KEY` が必要） |

### `GET /api/questions/next` レスポンス例

```json
{ "verb": "être", "tense": "présent", "pronoun": "je" }
```

### `POST /api/answers/check` リクエスト/レスポンス例

```json
// Request
{ "verb": "être", "tense": "présent", "pronoun": "je", "answer": "suis" }

// Response
{ "correct": true, "expected": "suis", "given": "suis" }
```

---

## テスト / CI の実行方法

### Backend

```bash
cd backend
uv sync --group dev

# lint
uv run ruff check .

# test
uv run pytest
```

### Frontend

```bash
cd frontend
npm install

# lint
npm run lint

# build
npm run build
```

### CI

`main` / `develop` ブランチへの push、または `main` への PR で GitHub Actions が自動実行されます。

| ジョブ | 内容 |
|--------|------|
| Backend (lint + test) | `uv run ruff check .` → `uv run pytest` |
| Frontend (build) | `npm run lint` → `npm run build` |

---

## 今後の開発方針

- **GitHub Issues 駆動**: 機能追加・バグ修正はすべてIssueを起点に行う
- **スモールPR**: 1 Issue = 1 PR、レビューしやすいサイズを保つ
- **スマホ実機確認**: UIに関わるPRは必ずスマホで動作確認してからマージ
- **AI活用**: Claude Code を使い Issue 単位で実装を進める

詳細は [docs/development_workflow.md](docs/development_workflow.md) を参照してください。

## 家庭内本番・外出先教材の運用設計

家庭内で本番学習し、外出先では承認済み教材だけを読み取る構成を [ADR 0001](docs/adr/0001-local-lan-and-remote-readonly-hosting.md) に記録しています。

家庭内本番の Compose・nginx・アクセス境界（運用化 Phase 1 / Issue #219）は `compose.production.yml` にあり、開発用の `docker compose up` とは別に次の wrapper から操作します。

```bash
cp production.env.example production.env          # 初回のみ。Git 管理外
docker volume create french-production-tutor-data   # 初回のみ。本番 DB の volume
bash scripts/production_compose.sh build
bash scripts/production_compose.sh run --rm --no-deps backend \
  python -m app.persistence.production initialize-empty-volume  # 初回の空volumeだけ
bash scripts/production_compose.sh up -d --wait
bash scripts/probe_production_boundary.sh 127.0.0.1 # 入口・非公開ポート・Host/Origin の確認
```

既定は `127.0.0.1:8080` だけで待ち受けます。LAN への公開、実機確認、firewall、sleep・再起動からの復旧は [家庭内本番の起動・復旧手順](docs/operations/local-lan-runbook.md) に従ってください。本番 DB は開発用と別の external volume にあり、コンテナを作り直しても残ります。通常起動は空 DB を作りません。

```bash
bash scripts/production_backup.sh                     # 起動中のまま整合バックアップを ~/FrenchTutorBackups に1つ作る
bash scripts/production_restore.sh <バックアップ.db>  # 停止 → 検査 → 差し替え（旧 DB は残す）→ 起動
```

バックアップは手動です。最後のバックアップより後の学習履歴と、同じ PC 上のバックアップは PC の故障・紛失で失われます（個人利用の割り切り）。保存先・復元・開発 DB の移行は [SQLite の保存先とバックアップ](docs/operations/sqlite-backup-runbook.md) を参照してください。
外出先向けには、本人が allowlist で選んだ一般教材だけを `snapshot.json` に書き出せます（DB は読み取り専用で開き、外部へは送信しません）。対象項目と手順は [外出先教材のデータ契約と書き出し手順](docs/operations/remote-readonly-contract.md) を参照してください。静的ビューアーと外部配布は未実装です。

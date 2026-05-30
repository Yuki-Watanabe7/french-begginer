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
| DB (初期) | SQLite（コード内辞書） |
| CI | GitHub Actions |

---

## ローカル起動方法

### 前提条件

- Docker / Docker Compose がインストールされていること

### 起動

```bash
docker compose up
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API ドキュメント: http://localhost:8000/docs

### 停止

```bash
docker compose down
```

---

## GitHub Codespaces での起動方法

1. GitHub リポジトリページで **Code → Codespaces → Create codespace on main** をクリック
2. Codespaces が起動したら、ターミナルで:
   ```bash
   docker compose up
   ```
3. 「ポート」タブに `5173` が表示されたら、ポートを **Public** に変更
4. 表示されたURLをコピーしてスマホブラウザで開く

---

## API 概要

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| GET | `/api/questions/next` | 次の問題を取得 |
| POST | `/api/answers/check` | 回答を送信して正誤判定 |

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

# lint
uv run ruff check .

# test
uv run pytest
```

### Frontend

```bash
cd frontend

npm install
npm run build
```

### CI

`main` および `develop` ブランチへの push / PR で GitHub Actions が自動実行されます。

---

## 今後の開発方針

- **GitHub Issues 駆動**: 機能追加・バグ修正はすべてIssueを起点に行う
- **スモールPR**: 1 Issue = 1 PR、レビューしやすいサイズを保つ
- **スマホ実機確認**: UIに関わるPRは必ずスマホで動作確認してからマージ
- **AI活用**: Claude Code を使い Issue 単位で実装を進める

詳細は [docs/development_workflow.md](docs/development_workflow.md) を参照してください。

# Architecture

## 全体構成

```
Browser (React + Vite)
    ↕ HTTP (JSON)
FastAPI (Python)
    ↕
SQLite (初期) → PostgreSQL (将来)
```

## Frontend / Backend 構成

| 項目 | 詳細 |
|------|------|
| Frontend | React 18 + TypeScript + Vite、スタイルはインラインCSSで最小構成 |
| Backend | FastAPI + Python 3.12、uvicorn でサーブ |
| Dev環境 | Docker Compose、Dev Container / GitHub Codespaces |
| CI | GitHub Actions (ruff, pytest, npm lint, npm build) |

## API 概要

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| GET | `/api/questions/next` | 次の問題を返す。クエリパラメータで絞り込み可能（下表参照） |
| POST | `/api/answers/check` | 回答の正誤判定 |

### GET /api/questions/next クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `group` | `all` \| `er` \| `ir` \| `irregular` | `all` | 動詞グループで絞り込み |
| `level` | `basic` \| `standard` \| `challenge` | （指定なし） | 難易度で絞り込み |
| `pattern` | `regular` \| `stem_change` \| `spelling_change` \| `irregular` | （指定なし） | 活用パターンで絞り込み |

複数パラメータを同時指定した場合はAND条件で絞り込まれる。
不正な値を指定した場合は `422 Unprocessable Entity`、条件に一致する動詞が存在しない場合は `404 Not Found` を返す。

例:
- `/api/questions/next?level=basic`
- `/api/questions/next?pattern=stem_change`
- `/api/questions/next?group=er&pattern=spelling_change`

## Backend 責務分担

```
backend/app/
├── api/          # HTTPリクエスト/レスポンスの受け取り・返却のみ
│   ├── questions.py
│   └── answers.py
├── domain/       # ビジネスルール（活用データ、モデル定義、判定ロジック）
│   └── conjugation.py
└── services/     # ユースケース（問題選択など、複数domainをまたぐ処理）
    └── question_service.py
```

- **api層**: FastAPIルーター。HTTPの関心事（パスパラメータ、ステータスコード）のみ担当。
- **domain層**: 活用データと判定ロジック。フレームワーク非依存。テストが書きやすい。
- **service層**: ユースケース実装。domain層を組み合わせてビジネスフローを実現。

## 動詞データ管理方針

動詞データは `backend/app/domain/conjugation.py` の3つの辞書で管理する。

| 辞書 | 役割 |
|------|------|
| `VERB_GROUPS` | 動詞グループ（`er` / `ir` / `irregular`）。APIの `?group=` フィルタに使用 |
| `CONJUGATIONS` | 全動詞の活用形データ（時制 → 主語 → 活用形） |
| `VERB_METADATA` | 分類メタデータ（`level` / `pattern`）。APIの `?level=` / `?pattern=` フィルタに使用 |

### 分類メタデータ仕様

**level**（頻出度・難易度）

| 値 | 意味 |
|----|------|
| `basic` | 最重要・初学者必須 |
| `standard` | 標準レベル |
| `challenge` | 応用・発展 |

**pattern**（活用パターン）

| 値 | 意味 |
|----|------|
| `regular` | 規則活用 |
| `stem_change` | 語幹変化あり |
| `spelling_change` | 綴り変化あり（発音保持目的） |
| `irregular` | 不規則活用 |

### 動詞を追加する際のルール

1. `VERB_GROUPS` にグループ（`er`/`ir`/`irregular`）を追加する
2. `CONJUGATIONS` に全6主語の直説法現在形を追加する
3. `VERB_METADATA` に `level` と `pattern` を追加する
4. `tests/test_api.py` に代表的なテストを1件以上追加する

> UIや学習モードを増やす前に、既存モードで自然に練習できるか確認すること。
> 新しい時制や例文の追加は別Issueで扱う。

## 将来的なDB拡張方針

現在は活用データをコード内辞書で保持しています。DB導入時の方針:

1. **SQLite → PostgreSQL 移行**
   - SQLAlchemy (非同期: `sqlalchemy[asyncio]`) + Alembic でマイグレーション管理
   - Docker Compose に `db` サービスを追加し、接続文字列を環境変数 `DATABASE_URL` で切り替え
   - SQLite: `sqlite+aiosqlite:///./french.db`
   - PostgreSQL: `postgresql+asyncpg://user:pass@db:5432/french`

2. **想定テーブル**
   - `verbs`: 動詞一覧
   - `conjugations`: (verb_id, tense, pronoun, form) の活用データ
   - `quiz_results`: ユーザーの回答履歴（ユーザー認証追加後）

3. **移行タイミング**
   - 学習履歴の永続化が必要になった時点でPostgreSQLへ移行
   - それまではSQLiteで十分

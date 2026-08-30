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
| GET | `/api/questions/next` | 動詞活用問題を1問返す。クエリパラメータで絞り込み可能（下表参照） |
| GET | `/api/questions/session` | セッション用に重複なしで最大`count`問の動詞活用問題を返す |
| POST | `/api/answers/check` | 動詞活用回答の正誤判定 |
| GET | `/api/nouns/next` | 名詞の性クイズ問題を1問返す。クエリパラメータで絞り込み可能（下表参照） |
| GET | `/api/nouns/session` | セッション用に重複なしで最大`count`問の名詞の性問題を返す |
| POST | `/api/nouns/check` | 名詞の性回答の正誤判定 |
| GET | `/api/nouns/article/next` | 冠詞+名詞クイズ問題を1問返す |
| GET | `/api/nouns/article/session` | セッション用に重複なしで最大`count`問の冠詞+名詞問題を返す |
| POST | `/api/nouns/article/check` | 冠詞+名詞回答の正誤判定 |
| GET | `/api/tts/speak` | フランス語テキストをOpenAI TTSで音声化してaudio/mpegを返す。`OPENAI_API_KEY`未設定時は503を返す |
| POST | `/api/tutor/sources` | 手入力の SourceDocument を作成する |
| GET | `/api/tutor/sources` | 保存済み Source の一覧（`created_at` 降順）。全文ではなく SourceSummary を返す |
| GET | `/api/tutor/sources/{source_id}` | SourceDocument を1件取得する |
| POST | `/api/tutor/sources/{source_id}/candidates/extract` | Source から学習候補を抽出し保存する。存在しない Source は 404。API key 未設定・一時障害は 503、LLM 応答不正は 502 |
| GET | `/api/tutor/sources/{source_id}/candidates` | Source 単位の Candidate 一覧。`status` と本文から再構成した `evidence_text` を含む。provider 生応答は返さない |
| POST | `/api/tutor/candidates/{candidate_id}/accept` | Candidate を採用し LearningItem を作成、または既存 Item へ SourceRef を追加する。再 accept は冪等。rejected からの accept は 409 |
| POST | `/api/tutor/candidates/{candidate_id}/reject` | Candidate を却下する。LearningItem は作らない。再 reject は冪等。accepted からの reject は 409 |
| POST | `/api/tutor/items` | 手入力の LearningItem を作成する |
| GET | `/api/tutor/items` | active な LearningItem 一覧。管理検索はしない |
| GET | `/api/tutor/items/{item_id}` | LearningItem と現在の LearnerState / ReviewSchedule を返す |
| GET | `/api/tutor/items/{item_id}/exercises/{exercise_type}` | Tutor Exercise を再構成して返す。正解は含めない |
| POST | `/api/tutor/items/{item_id}/exercises/{exercise_type}/answer` | Exercise を server-side で採点し、LearningEvent / LearnerState / ReviewSchedule を更新する |
| POST | `/api/tutor/practice/sessions` | active LearningItem から Practice Session を組み立てる。Session 自体は永続化しない |
| POST | `/api/tutor/items/{item_id}/reviews` | 復習イベントを記録し、LearnerState と ReviewSchedule を更新する |
| GET | `/api/tutor/reviews/due` | 現在 due の LearningItem を返す。任意時刻の query は持たない |

### GET /api/tutor/sources クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `limit` | 1〜100 の整数 | `50` | 取得件数。`created_at` 降順（同一時刻は `id` 昇順）。不正値は 422 |

レスポンスは全文ではなく `SourceSummary`（`content_preview` は先頭120文字）。0件でも 200 + `[]`。

### GET /api/tutor/items クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `limit` | 1〜100 の整数 | `50` | 取得件数。`created_at` 昇順（同一時刻は `id` 昇順）。active のみ。不正値は 422 |

0件でも 200 + `[]`。suspended / mastered は含めない。

### POST /api/tutor/practice/sessions

active な LearningItem から連続練習用の Session を組み立てる。Session 自体は DB に保存せず、学習履歴は回答ごとの LearningEvent が source of truth。

| フィールド | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `source_id` | string optional | （なし） | 指定 Source 由来の Item だけを対象にする |
| `item_ids` | string[] optional | （なし） | 明示した Item だけを対象にする |
| `question_count` | 1〜20 の整数 | `5` | 上限。候補が少なければ水増しせず短く返す |
| `seed` | string optional | サーバー既定 | 選択順の再現用。Exercise 本文の再構成には使わない |

`source_id` と `item_ids` の同時指定は 422。どちらも無ければ active Item 全体から選ぶ。存在しない Source / Item は 404。0件でも 200。

レスポンス:

| フィールド | 説明 |
|------------|------|
| `session_id` | エフェメラルな識別子。再取得 API は持たない |
| `exercises` | `PublicExercise` の配列。正解・metadata は含めない |
| `skipped_items` | 生成できなかった Item と `skip_reason` |
| `requested_count` | 要求した出題数 |
| `generated_count` | 実際に入れた出題数（`<= requested_count`） |

due / overdue / mastery による並び替えはしない（Phase 4）。

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

### GET /api/nouns/next クエリパラメータ

| パラメータ | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `level` | `basic` \| `standard` \| `challenge` | （指定なし） | 難易度で絞り込み |
| `category` | `person` \| `home` \| `food` \| `place` \| `time` \| `school` \| `nature` \| `abstract` | （指定なし） | カテゴリで絞り込み |

複数パラメータを同時指定した場合はAND条件で絞り込まれる。
不正な値を指定した場合は `422 Unprocessable Entity`、条件に一致する名詞が存在しない場合は `404 Not Found` を返す。

例:
- `/api/nouns/next?level=basic`
- `/api/nouns/next?category=food`
- `/api/nouns/next?level=basic&category=home`

レスポンス例:
```json
{"noun": "livre", "meaning_ja": "本", "article_indefinite": "un"}
```

### POST /api/nouns/check

リクエスト: `{"noun": "livre", "answer": "masculine" | "feminine"}`

レスポンス: `{"correct": true, "expected": "masculine", "given": "masculine"}`

未知の名詞を指定した場合は `400 Bad Request`、不正な `answer` 値は `422 Unprocessable Entity` を返す。

## Backend 責務分担

```
backend/app/
├── api/          # HTTPリクエスト/レスポンスの受け取り・返却のみ
│   ├── questions.py
│   ├── answers.py
│   ├── nouns.py
│       ├── tutor.py              # Tutor最小API（Issue #112）、Candidate 採否（Issue #134）、Exercise 回答（Issue #149）、Practice Session（Issue #150）
├── domain/       # ビジネスルール（活用データ、モデル定義、判定ロジック）
│   ├── conjugation.py
│   ├── noun.py
│   ├── tutor.py              # Tutor機能の中核モデル（docs/tutor_architecture.md）
│   ├── candidate_normalization.py  # 抽出Candidateの検証・正規化・重複統合（Issue #133）
│   ├── review_scheduler.py   # 初期復習間隔の算出（Issue #111）
│   ├── exercise.py           # LearningItem→Exercise契約（Issue #145）
│   ├── exercise_generation.py
│   ├── exercise_evaluation.py  # Tutor Exercise の server-side 採点（Issue #149）
│   ├── practice_session.py   # active LearningItem から Practice Session を組み立てる（Issue #150）
│   └── conjugation_adapter.py
├── evaluation/   # LLM抽出の固定fixtureと品質チェック（Issue #136）。HTTPからは使わない
├── persistence/  # Tutorデータの SQLite / schema version（ORMはここまで）
├── repositories/ # Tutorデータの永続化境界（Protocol + SQLite実装）
└── services/     # ユースケース（問題選択など、複数domainをまたぐ処理）
    ├── question_service.py
    ├── noun_service.py
    ├── learning_state_service.py  # LearningEvent → LearnerState 更新
    ├── review_service.py          # 復習予定の保存と due 取得
    ├── tutor_service.py           # Tutor最小APIのユースケース
    ├── extraction_service.py      # Source から Candidate を抽出し正規化する
    ├── candidate_service.py       # 抽出結果の保存と accept/reject（Issue #134）
    ├── exercise_service.py        # Exercise 取得・採点・LearningEvent 記録（Issue #149）
    └── practice_session_service.py  # Practice Session 組み立て（Issue #150）
```

- **api層**: FastAPIルーター。HTTPの関心事（パスパラメータ、ステータスコード）のみ担当。
- **domain層**: 活用データと判定ロジック。フレームワーク非依存。テストが書きやすい。
- **persistence / repository層**: Tutor可変データの永続化。serviceは Protocol に依存し、SQLite を直接見ない。
- **service層**: ユースケース実装。domain層を組み合わせてビジネスフローを実現。

> Tutor機能（Source取り込み〜長期復習）のドメインモデル設計は [tutor_architecture.md](./tutor_architecture.md) を参照。
> Phase 0 の学習ループ（Source -> Item -> Event -> State -> Schedule -> due）は
> `backend/tests/test_tutor_vertical_slice.py` で統合テストする。
> Phase 1 の Text Source Ingestion（手動貼り付け → 永続化 → 一覧 → 詳細）は
> `backend/tests/test_tutor_phase1_vertical_slice.py` と
> `frontend/src/test/TutorPhase1Flow.test.tsx` で統合テストする。
> Phase 2 の LLM抽出品質（固定 fixture と deterministic checks）は
> [tutor_extraction_quality.md](./tutor_extraction_quality.md) を参照。
> Phase 2 の Source → Candidate → LearningItem vertical slice は
> `backend/tests/test_tutor_phase2_vertical_slice.py` と
> `frontend/src/test/TutorPhase2Flow.test.tsx` で統合テストする。
> Phase 3 の Practice Session UI は
> `frontend/src/test/PracticeSessionFlow.test.tsx` で統合テストする。

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

## 学習モード抽象化の設計方針

> このセクションは実装ではなく設計メモである。名詞版クイズなど動詞活用以外の学習モードを将来追加する際の指針として記載する。

### 現状整理

現在の学習モードは `verb_conjugation`（動詞活用練習）相当の1モードのみ。

**現在の `Question` 型（動詞活用専用）**

```ts
// Frontend: src/types.ts
type Question = {
  verb: string
  tense: string
  pronoun: string
}
```

```python
# Backend: app/domain/conjugation.py
class Question(BaseModel):
    verb: str
    tense: str
    pronoun: str
```

**動詞活用前提になっている主要箇所**

| 箇所 | 依存内容 |
|------|----------|
| `GET /api/questions/next` | `verb` / `tense` / `pronoun` を返す |
| `POST /api/answers/check` | `{verb, tense, pronoun, answer}` を受け取る |
| `QuizCard` コンポーネント | `pronoun` を表示し動詞活用の入力を促す |
| `SessionResult` コンポーネント | 誤答を `verb + pronoun` 形式で一覧表示 |
| `useQuiz.ts` | `Question` を動詞活用専用として扱う |

このまま名詞版を直接追加すると、`Question` に optional field が増えて型安全性と見通しが悪化する恐れがある。

### 将来の学習モード案

最低限、以下2種類を想定する:

| モード | 内容 |
|--------|------|
| `verb_conjugation` | 動詞活用練習（現行モード） |
| `noun_gender` | 名詞の性クイズ（`le` / `la` を答える） |

### 型・API設計の方向性

discriminated union（判別共用体）パターンを用いて、`mode` フィールドで型を分岐させる。

**Frontend 型設計案**

```ts
type QuizMode = 'verb_conjugation' | 'noun_gender'

type VerbQuestion = {
  mode: 'verb_conjugation'
  verb: string
  tense: string
  pronoun: string
}

type NounGenderQuestion = {
  mode: 'noun_gender'
  noun: string
  meaning?: string
}

type Question = VerbQuestion | NounGenderQuestion
```

**Backend 型設計案**

```python
from typing import Literal
from pydantic import BaseModel

class VerbQuestion(BaseModel):
    mode: Literal["verb_conjugation"]
    verb: str
    tense: str
    pronoun: str

class NounGenderQuestion(BaseModel):
    mode: Literal["noun_gender"]
    noun: str
    meaning: str | None = None

Question = VerbQuestion | NounGenderQuestion
```

**API変更案**

`/api/questions/next` に `mode` クエリパラメータを追加:

```
GET /api/questions/next?mode=verb_conjugation  # 現行と互換
GET /api/questions/next?mode=noun_gender
```

レスポンスに `mode` フィールドを含め、クライアントが型を判別できるようにする。

### 移行方針

名詞版MVP実装時に必要最小限の抽象化を行う。段階的に進める:

1. **現時点（このIssue）**: ドキュメント化のみ。既存APIとコードは変更しない
2. **名詞版MVP実装時**: 以下の箇所を最小限変更する
   - `Question` 型を discriminated union へ変更（Backend・Frontend 両方）
   - `/api/questions/next` に `mode` パラメータ追加（デフォルト `verb_conjugation` で後方互換を維持）
   - `/api/answers/check` を `mode` に応じた判定ロジックに分岐
   - `QuizCard` を `mode` で描画を切り替え（`verb_conjugation` の動作は変更しない）
3. **大規模汎用化はしない**: 汎用クイズエンジン化・プラグイン構造などは過剰設計。モード追加ごとに必要最小限の分岐を追加する方針とする

### 名詞版MVP実装時に変更すべき主要箇所

| ファイル | 変更内容 |
|----------|----------|
| `backend/app/domain/conjugation.py` | `NounGenderQuestion` モデル追加、名詞データ辞書追加 |
| `backend/app/api/questions.py` | `mode` クエリパラメータ追加 |
| `backend/app/api/answers.py` | `mode` に応じた判定分岐 |
| `backend/app/services/question_service.py` | `mode` に応じた問題選択ロジック追加 |
| `frontend/src/types.ts` | `Question` を discriminated union に変更 |
| `frontend/src/hooks/useQuiz.ts` | `mode` に応じた状態管理分岐 |
| `frontend/src/components/QuizCard.tsx` | `mode` に応じた表示切り替え |
| `frontend/src/components/SessionResult.tsx` | `mode` に応じた誤答表示切り替え |

## 将来的なDB拡張方針

### 現状（Issue #109）

Tutor機能の可変ユーザーデータだけを SQLite に永続化する。

- 対象: `SourceDocument` / `LearningItem` / `LearningEvent` /
  `LearnerState` / `ReviewSchedule`
- 実装: SQLAlchemy 2.x（同期）+ Repository Protocol
- 接続: 環境変数 `TUTOR_DATABASE_URL`（未指定時は `backend/data/tutor.db`）
- schema version: `schema_migrations` テーブル（Alembic は未導入）
- 動詞・名詞の正解データは `conjugation.py` / `noun.py` のコード内管理のまま

詳細は [tutor_architecture.md](./tutor_architecture.md) の永続化層を参照。

### 将来

1. **SQLite → PostgreSQL 移行**
   - SQLAlchemy の接続先を切り替える
   - 連続した schema 変更または複数環境向け migration が必要になった時点で Alembic を導入する
   - Docker Compose に `db` サービスを追加し、接続文字列を環境変数で切り替える
   - SQLite: `sqlite:///./data/tutor.db`
   - PostgreSQL: `postgresql+asyncpg://user:pass@db:5432/french`

2. **動詞・名詞データのDB移行は別Issue**
   - 既存クイズの正解データは、Tutor永続化とは独立してコード内辞書を維持する

3. **移行タイミング**
   - ユーザー認証・複数環境・PostgreSQL が必要になった時点
   - 単一学習者のローカル履歴だけなら SQLite で十分

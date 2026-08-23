# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (`cd backend`)

```bash
uv sync --extra dev          # 依存関係インストール（初回 or pyproject.toml 変更後）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # 開発サーバー起動
uv run ruff check .          # lint
uv run pytest                # 全テスト
uv run pytest tests/test_api.py::test_health  # 単一テスト
```

### Frontend (`cd frontend`)

```bash
npm install        # 依存関係インストール（初回 or package.json 変更後）
npm run dev        # 開発サーバー起動（port 5173）
npm run lint       # ESLint
npm run build      # TypeScript 型チェック + Vite ビルド
```

### 両サービス同時起動

```bash
docker compose up
```

Frontend: `http://localhost:5173` / Backend: `http://localhost:8000` / API docs: `http://localhost:8000/docs`

---

## Architecture

### Backend 3層構造

```
backend/app/
├── api/           # HTTP の関心事のみ（パス・ステータスコード・Pydantic モデルの受け渡し）
├── domain/        # ビジネスルール。フレームワーク非依存
│   ├── conjugation.py  # 活用データ辞書・Pydantic モデル・判定ロジック
│   └── review_scheduler.py  # 初期復習間隔の算出
├── persistence/   # Tutorデータの SQLite / schema version
├── repositories/  # Tutorデータの永続化境界（Protocol + SQLite実装）
└── services/      # ユースケース（domain を組み合わせる処理）
    ├── question_service.py  # グループフィルタ付きランダム問題選択
    ├── learning_state_service.py  # LearningEvent から LearnerState を更新
    ├── review_service.py  # 復習予定の保存と due 取得
    └── tutor_service.py  # Tutor最小APIのユースケース
```

新しい動詞を追加する場合は `CONJUGATIONS` と `VERB_GROUPS` の両方を `conjugation.py` に追記する。`VerbGroup` は `Literal["all", "er", "ir", "irregular"]` で、`?group=` クエリパラメータで絞り込める。

### Frontend フェーズ状態機械

`useQuiz.ts` の `Phase` 型が UI 全体を駆動する。遷移:

```
setup → quiz-settings → loading → answering ⇄ result
                                              ↓ (セッション完了 or 復習フェーズ終了)
                                        session-result
```

`isReviewPhase` フラグが立つと、通常セッション終了後に誤答問題を再出題する復習フェーズに入る。`reviewQueue` は復習問題のキューで、空になったら `session-result` へ遷移する。

`stateRef` は非同期コールバック（`submit`, `nextQuestion` など）が古い state を参照しないための回避策。コールバック内では `stateRef.current` から最新値を取得し、`setState` の更新には関数形式 `setState(s => ...)` を使う。

### Frontend コンポーネント構成

`App.tsx` が `useQuiz` を使いフェーズに応じてコンポーネントを切り替える:

| フェーズ | コンポーネント |
|----------|---------------|
| `setup` | `VerbGroupSelector` — 動詞グループ選択 |
| `quiz-settings` | `QuizSettings` — 出題数選択（5/10/20問） |
| `answering` / `result` | `QuizCard` — 問題表示・入力・正誤フィードバック |
| `session-result` | `SessionResult` — 初回正答率・復習結果・誤答一覧 |

スタイルはすべてインライン CSS（`Record<string, React.CSSProperties>`）。外部 CSS フレームワークは使わない。

### API

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| GET | `/api/questions/next?group=all` | ランダム問題取得。`group` は `all`/`er`/`ir`/`irregular` |
| POST | `/api/answers/check` | `{verb, tense, pronoun, answer}` → `{correct, expected, given}` |
| POST | `/api/tutor/sources` | 手入力 SourceDocument の作成 |
| GET | `/api/tutor/items/{item_id}` | LearningItem と LearnerState / ReviewSchedule |
| POST | `/api/tutor/items/{item_id}/reviews` | 復習イベント記録（state / schedule も更新） |
| GET | `/api/tutor/reviews/due` | 現在 due の LearningItem |

### 現在の動詞データ（`conjugation.py`）

| グループ | 動詞 |
|----------|------|
| `-er` | parler, aimer, travailler |
| `-ir` | finir, choisir |
| 不規則 | être, avoir, aller, faire |

現時点では `présent` のみ。

### Vite プロキシ

`vite.config.ts` で `/api` と `/health` を `http://backend:8000`（Docker サービス名）にプロキシ。Docker 外で frontend 単独起動する場合は `VITE_API_BASE=http://localhost:8000 npm run dev` で上書きする。

---

## 開発方針

- 1 Issue = 1 PR。UIに関わる変更はスマホ実機（Codespaces ポートフォワード）で確認してからマージ
- PR 前に `ruff check .` / `pytest` / `npm run lint` / `npm run build` がすべて通ること
- API を追加・変更した場合は `docs/architecture.md` の API 表を更新する

## 作業完了条件

Claude は作業完了報告の前に、必ず`bash scripts/quality-check.sh`を実行すること。
実行できない場合は、完了報告してはならない。
その場合は以下を報告すること。

1. 実行できなかったコマンド
2. エラーメッセージ
3. 原因推定
4. ユーザー側で必要な対応

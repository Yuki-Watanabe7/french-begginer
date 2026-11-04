# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (`cd backend`)

```bash
uv sync --group dev          # 依存関係インストール（初回 or pyproject.toml 変更後）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # 開発サーバー起動
uv run ruff check .          # lint
uv run pytest                # 全テスト
uv run pytest tests/test_api.py::test_health  # 単一テスト
    uv run python ../scripts/evaluate_tutor_extraction.py  # Tutor抽出の実LLM品質評価（任意。OPENAI_API_KEY が必要）
    uv run python ../scripts/evaluate_tutor_recommendations.py  # Tutor推薦品質の固定fixture評価（任意。LLM不要）
    uv run python ../scripts/evaluate_tutor_learning_quality.py  # Tutor学習品質の複数日シミュレーション（任意。LLM不要）
    uv run python ../scripts/rebuild_review_schedules.py --check  # ReviewSchedule 不整合の検出（任意）
    uv run python ../scripts/export_public_snapshot.py export --database <DBコピー> --allowlist <allowlist.json>  # 許可した教材だけを公開 Snapshot に書き出す（任意。DB は変更しない）
    uv run python ../scripts/prepare_public_readonly.py --snapshot <snapshot.json> --out <Git外の新規フォルダー>  # 専用画面のビルド後、配布候補だけを梱包（#223。通信なし）
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

### 家庭内本番（`compose.production.yml`、Issue #219）

```bash
bash scripts/production_compose.sh up -d --build --wait   # -f / -p / --env-file を固定した wrapper。dev と重ねない
bash scripts/production_compose.sh exec backend python -m app.persistence.readiness  # DB の開閉・schema・書込確認
bash scripts/probe_production_boundary.sh 127.0.0.1       # 入口 8080 のみ・Host / Origin / TTS 境界の外形確認
bash scripts/production_backup.sh                         # 整合バックアップを ~/FrenchTutorBackups に1つ作る（起動中のまま）
bash scripts/production_restore.sh <backup.db>            # 停止→検査→差し替え（旧DBは残す）→起動
```

外出先向けの公開 Snapshot は本番 DB を直接読まず、バックアップのコピーから書き出す（`docs/operations/remote-readonly-contract.md`、Issue #221）。

本番 DB は external volume `french-production-tutor-data`。通常起動は既存 DB を必須とし、空 DB を作らない（初回だけ明示初期化）。バックアップは手動の整合コピーだけで、暗号化・別機器コピー・世代管理・復元演習は要件にしない（Issue #220 の簡素化）。手順と割り切りは `docs/operations/sqlite-backup-runbook.md`。

本番は `APP_ENV=production` で CORS を外し、`app/api/request_guard.py` が Host（`APP_ALLOWED_HOSTS` + loopback）、書込の Origin / Sec-Fetch-Site、TTS の `X-French-Tutor-Request` ヘッダーを検証する。手順は `docs/operations/local-lan-runbook.md`。

---

## Architecture

### Backend 3層構造

```
backend/app/
├── api/           # HTTP の関心事のみ（パス・ステータスコード・Pydantic モデルの受け渡し）
├── domain/        # ビジネスルール。フレームワーク非依存
│   ├── conjugation.py  # 活用データ辞書・Pydantic モデル・判定ロジック
│   ├── review_scheduler.py  # 初期復習間隔の算出
│   ├── review_queue.py  # direction-awareなdue review queue（Issue #163）
│   ├── review_session.py  # due queueからReview Practice Sessionを組み立てる（Issue #164）
│   ├── recommendation_signal.py  # 推薦入力のsignal snapshot（Issue #175）
│   ├── recommendation_ranking.py  # 説明可能なranking policy（Issue #176）
│   ├── daily_learning_plan.py  # 新規/復習の配分 Daily Learning Plan（Issue #177）
│   ├── adaptive_plan.py  # 復習負債・誤答率に応じた今日の件数調整（Issue #204）
│   ├── source_learning_summary.py  # Source単位の学習成果（Issue #205）
│   ├── admission_policy.py  # 新規LearningItemの流入制御 admission policy（Issue #200）
│   ├── known_item_policy.py # 既知項目の explicit known と conservative auto-skip（Issue #201）
│   ├── context_selection.py # 複数Source文脈の context rotation（Issue #202）
│   ├── weakness_pattern.py  # 複数Item横断の苦手パターン（Issue #203）
│   ├── today_session.py  # 今日の学習 Plan 公開表現と Session 生成（Issue #178）
│   ├── public_snapshot.py  # 外出先 Read-Only 向け公開 Snapshot（public-v1）の DTO・検査（Issue #221）
│   ├── candidate_normalization.py  # 抽出Candidateの検証・正規化・重複統合
│   ├── exercise.py  # LearningItem→Exerciseの契約・eligibility・skill direction
│   ├── exercise_generation.py  # LearningItemからのdeterministic Exercise生成（vocab/expression/cloze/conjugation adapter）
│   ├── exercise_evaluation.py  # Tutor Exercise の server-side 採点（Issue #149）
│   ├── practice_session.py  # active LearningItem から Practice Session を組み立てる（Issue #150）
│   ├── conjugation_adapter.py  # conjugation Item→既存動詞活用への安全な接続
│   └── source_ingestion.py  # Source ingestion 共通契約（Issue #189）
├── ingestion/     # Web URL、PDF、YouTube 字幕、SRT / VTT、音声、テキスト / 会話 JSON（Issue #190 / #191 / #192 / #193 / #194）
├── evaluation/    # 抽出品質（Issue #136）、推薦品質fixture（Issue #180）、長期学習品質（Issue #206）
├── persistence/   # Tutorデータの SQLite / schema version
├── repositories/  # Tutorデータの永続化境界（Protocol + SQLite実装）
└── services/      # ユースケース（domain を組み合わせる処理）
    ├── question_service.py  # グループフィルタ付きランダム問題選択
    ├── learning_state_service.py  # LearningEvent から LearnerState を更新
    ├── review_service.py  # 復習予定の保存と due 取得
    ├── review_schedule_rebuilder.py  # Event履歴からReviewSchedule再構築（Issue #166）
    ├── tutor_service.py  # Tutor最小APIのユースケース
    ├── source_ingestion_service.py  # ingestion 結果の再利用 / 版追加（Issue #189）
    ├── web_url_ingestion.py  # Web URL 取り込み（Issue #190）
    ├── pdf_ingestion.py  # テキスト PDF 取り込み（Issue #191）
    ├── youtube_ingestion.py  # YouTube 公開字幕の取り込み（Issue #192）
    ├── subtitle_ingestion.py  # SRT / VTT 取り込み（Issue #192）
    ├── audio_ingestion.py  # 音声の文字起こし取り込み（Issue #193）
    ├── text_file_ingestion.py  # テキスト / Markdown 取り込み（Issue #194）
    ├── conversation_ingestion.py  # 会話 JSON 取り込み（Issue #194）
    ├── extraction_service.py  # Source から LearningItemCandidate を抽出
    ├── candidate_service.py  # 抽出結果の保存と accept/reject
    ├── exercise_service.py  # Exercise 取得・採点・LearningEvent 記録
    ├── practice_session_service.py  # Practice Session 組み立て
    ├── review_session_service.py  # Review Practice Session 組み立て
    ├── weakness_pattern_service.py  # 苦手パターンの算出（Issue #203）
    ├── source_learning_summary_service.py  # Source単位の学習成果（Issue #205）
    ├── today_learning_service.py  # 今日の学習 Plan / Session（Issue #178）。件数省略時は負荷を自動調整（Issue #204）
    └── public_snapshot_export.py  # allowlist の教材だけを snapshot.json に書き出す（Issue #221）
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

`App.tsx` がモードと `useQuiz` のフェーズに応じてコンポーネントを切り替える:

| フェーズ | コンポーネント |
|----------|---------------|
| モード選択 | `ModeSelector` — 動詞 / 名詞 / 冠詞 / 自分の教材 |
| `tutor` | `TutorFlow` — Source 一覧 / 「今日の学習」 / 「今日の復習」 / 複数形式の教材追加 / 詳細（Candidate 抽出・採否） / Practice Session / Review Session / Today Session |
| `setup` | `VerbGroupSelector` — 動詞グループ選択 |
| `quiz-settings` | `QuizSettings` — 出題数選択（5/10/20問） |
| `answering` / `result` | `QuizCard` — 問題表示・入力・正誤フィードバック |
| `session-result` | `SessionResult` — 初回正答率・復習結果・誤答一覧 |

教材追加は `TutorSourceForm` で、貼り付け / Web URL / PDF / YouTube・字幕 / 音声 / 会話ログ・テキストファイルを同じ画面から選ぶ。取り込み後は既存の Source 詳細と Candidate UI を使う。

Tutor Practice Session は `TutorFlow` 内で `QuizSettings` → `PracticeSessionFlow` へ進む。`usePracticeSession` が出題・採点・結果を駆動し、choice / text / reconstruction を `PracticeExerciseCard` が描画する。

「今日の学習」は Tutor 一覧の `TutorTodayLearningCard` が review/new 件数と推薦理由を表示し、同じ `PracticeSessionFlow`（`kind: 'today'`）で Today Session を開始する。出題数選択は挟まない。

「今日の復習」は Tutor 一覧の `TutorTodayReviewCard` が due 件数を表示し、due > 0 なら同じ `PracticeSessionFlow`（`kind: 'review'`）で Review Session を開始する。純復習導線では新規学習と復習は混ぜない。

スタイルはすべてインライン CSS（`Record<string, React.CSSProperties>`）。外部 CSS フレームワークは使わない。

### API

| Method | Path | 説明 |
|--------|------|------|
| GET | `/health` | ヘルスチェック |
| GET | `/api/questions/next?group=all` | ランダム問題取得。`group` は `all`/`er`/`ir`/`irregular` |
| POST | `/api/answers/check` | `{verb, tense, pronoun, answer}` → `{correct, expected, given}` |
| POST | `/api/tutor/sources` | 手入力 SourceDocument の作成 |
| POST | `/api/tutor/sources/ingest/url` | Web URL から SourceDocument を作成。同一 URL・同一本文は既存を返す |
| POST | `/api/tutor/sources/ingest/pdf` | テキスト PDF をページ位置付き SourceDocument にする。同一ファイル・同一本文は既存を返す。OCR はしない |
| POST | `/api/tutor/sources/ingest/youtube` | YouTube の公開字幕を時刻付き SourceDocument にする。同一動画・同一本文は既存を返す。音声 download はしない |
| POST | `/api/tutor/sources/ingest/subtitle` | SRT / VTT を時刻付き SourceDocument にする。同一ファイル・同一本文は既存を返す |
| POST | `/api/tutor/sources/ingest/audio` | 音声を文字起こし、時刻付き SourceDocument にする。同一音声・同一本文は既存を返す。raw audio は保存しない |
| POST | `/api/tutor/sources/ingest/text-file` | テキスト / Markdown を plain text の SourceDocument にする。同一ファイル・同一本文は既存を返す。リンク先は取得しない |
| POST | `/api/tutor/sources/ingest/conversation` | structured conversation JSON を話者・発話時刻付き SourceDocument にする。同一ファイル・同一本文は既存を返す。未知の JSON は解釈しない |
| GET | `/api/tutor/sources` | 保存済み Source の一覧（`SourceSummary`） |
| GET | `/api/tutor/sources/{source_id}` | SourceDocument を1件取得 |
| GET | `/api/tutor/sources/{source_id}/learning-summary` | この Source に関連する項目の現在の学習状態。結果は保存しない |
| POST | `/api/tutor/sources/{source_id}/candidates/extract` | Source から Candidate を抽出して保存。再実行しても重複爆発しない |
| GET | `/api/tutor/sources/{source_id}/candidates` | Source 単位の Candidate 一覧（status / evidence_text） |
| POST | `/api/tutor/candidates/{candidate_id}/accept` | Candidate を採用し LearningItem を作成または既存へ統合 |
| POST | `/api/tutor/candidates/{candidate_id}/reject` | Candidate を却下する。LearningItem は作らない |
| GET | `/api/tutor/items` | active な LearningItem 一覧 |
| GET | `/api/tutor/items/{item_id}` | LearningItem と LearnerState / ReviewSchedule（direction 別 `review_schedules` を含む） |
| GET | `/api/tutor/items/{item_id}/exercises/{exercise_type}` | Tutor Exercise 取得（正解は含めない） |
| POST | `/api/tutor/items/{item_id}/exercises/{exercise_type}/answer` | Exercise を server-side で採点し LearningEvent を記録 |
| POST | `/api/tutor/practice/sessions` | active LearningItem から Practice Session を組み立てる（永続化しない） |
| POST | `/api/tutor/review/sessions` | due review queue から Review Practice Session を組み立てる（永続化しない） |
| GET | `/api/tutor/today` | 今日の学習 Plan（review/new 配分と説明可能な reason） |
| POST | `/api/tutor/today/sessions` | 今日の学習 Plan から Tutor Today Session を組み立てる（永続化しない） |
| POST | `/api/tutor/items/{item_id}/reviews` | 復習イベント記録（state / schedule も更新） |
| GET | `/api/tutor/reviews/due` | 現在 due の LearningItem |
| GET | `/api/tutor/reviews/queue` | direction-aware な due review queue（件数 summary 付き） |
| POST | `/api/tutor/items/{item_id}/known` | 既知として新規学習から外す。再指定は冪等。status は変えない。due review は残す |
| POST | `/api/tutor/items/{item_id}/known/undo` | 既知指定を取り消す。未指定でも冪等 |
| GET | `/api/tutor/items/{item_id}/known` | explicit known の現在値と更新時刻。未指定でも Item があれば 200 |

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

- 実装ブランチは `origin/main` から切る。Cloud Agent の checkout は起動時のスナップショットで、リモートの `main` より遅れていることがある。ブランチを切る前、および作業完了前に `bash scripts/ensure_branch_includes_main.sh` を実行する。失敗したら `git fetch origin main` のあと `origin/main` から切り直すか、`git merge origin/main` で取り込んでから続ける。ローカルの `main` やスナップショットの HEAD からは切らない
- 1 Issue = 1 PR。UIに関わる変更はスマホ実機（Codespaces ポートフォワード）で確認してからマージ
- PR 前に `ruff check .` / `pytest` / `npm run lint` / `npm run build` がすべて通ること
- API を追加・変更した場合は `docs/architecture.md` の API 表を更新する

## PR の Test plan

PR 本文の Test plan は「これから人が確認するリスト」ではなく、**この作業で確認した事実の記録**である。

- エージェントが自動テストや `quality-check.sh` で確認して通した項目は `[x]` にする
- 人手確認が不要な項目を、前回 PR の体裁に合わせて未チェックのまま残さない
- `[ ]` にしてよいのは、スマホ実機の使用感など、本当に人が見る必要がある項目だけ
- 確認に使ったテスト名を括弧書きする（例: `test_create_and_get_source`）

## 作業完了条件

Claude は作業完了報告の前に、必ず`bash scripts/quality-check.sh`を実行すること。
このスクリプトは最初に `scripts/ensure_branch_includes_main.sh` を実行し、HEAD が `origin/main` を含まなければテストの前に失敗する。
実行できない場合は、完了報告してはならない。
その場合は以下を報告すること。

1. 実行できなかったコマンド
2. エラーメッセージ
3. 原因推定
4. ユーザー側で必要な対応

PR を作成・更新する場合は、上記 Test plan ルールに従い、確認済み項目を `[x]` にしてから提出すること。

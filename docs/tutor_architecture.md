# Tutor Architecture

関心ベースの個人フランス語家庭教師機能（Roadmap: Issue #107）の設計ドキュメント。

このドキュメントは Phase 0 の中核ドメインモデル（Issue #108）、
永続化層（Issue #109）、学習状態更新（Issue #110）、
初期 Review Scheduler（Issue #111）、最小 API（Issue #112）、
vertical slice 統合テスト（Issue #113）、
Phase 1 の Source 一覧 API（Issue #121）、Frontend 型と API client（Issue #122）、
手入力保存画面（Issue #123）、一覧・詳細画面（Issue #124）、
Phase 1 vertical slice（Issue #125）、
Phase 2 の LearningItemCandidate ドメインと永続化（Issue #131）、
LLM Extraction Service（Issue #132）、
抽出 Candidate の検証・正規化・重複統合（Issue #133）、
抽出・採否 API（Issue #134）、
Source 詳細の Candidate レビュー UI（Issue #135）、
LLM抽出品質の固定 fixture・評価ハーネス（Issue #136）、
Phase 2 vertical slice と Exit Criteria（Issue #137）、
および Phase 3 の LearningItem → Exercise 契約（Issue #145）、
vocabulary / expression 向け deterministic Exercise 生成（Issue #146）、
Source evidence からの cloze Exercise 生成（Issue #147）、
conjugation LearningItem の既存動詞活用 adapter（Issue #148）、
Exercise の server-side 採点と LearningEvent 記録（Issue #149）、
accepted LearningItem からの Practice Session 組み立て（Issue #150）、
Tutor Practice Session の Frontend UI と TTS/feedback（Issue #151）、
Phase 3 vertical slice と Exit Criteria（Issue #152）、
および Phase 4 の recognition / production 別 LearnerState 集計（Issue #161）、
ReviewSchedule の direction 分離（Issue #162）、
direction-aware な due review queue（Issue #163）、
due queue からの Review Practice Session（Issue #164）、
「今日の復習」Frontend 導線（Issue #165）、
LearningEvent / LearnerState / ReviewSchedule の原子性と schedule 再構築（Issue #166）、
Phase 4 vertical slice と Exit Criteria（Issue #167）
の責務分離・不変条件を記録する。

- ドメイン: `backend/app/domain/tutor.py` / `backend/tests/test_tutor_domain.py`
- 永続化: `backend/app/repositories/` / `backend/app/persistence/`
  / `backend/tests/test_tutor_persistence.py`
- 状態更新: `backend/app/services/learning_state_service.py`
  / `backend/tests/test_learning_state_service.py`
  （`by_direction` 集計は Issue #161）
- 復習予定: `backend/app/domain/review_scheduler.py`
  / `backend/app/services/review_service.py`
  / `backend/tests/test_review_scheduler.py`
  / `backend/tests/test_review_service.py`
  （direction 別 schedule は Issue #162）
- due review queue: `backend/app/domain/review_queue.py`
  / `backend/tests/test_review_queue.py`
  （Issue #163）
- Review Practice Session: `backend/app/domain/review_session.py`
  / `backend/app/services/review_session_service.py`
  / `backend/tests/test_review_session.py`
  / `backend/tests/test_review_session_service.py`
  / `backend/tests/test_review_session_api.py`
  （Issue #164）
- 「今日の復習」Frontend: `frontend/src/hooks/useReviewQueue.ts`
  / `frontend/src/components/TutorTodayReviewCard.tsx`
  / `frontend/src/test/TutorTodayReviewCard.test.tsx`
  / `frontend/src/test/TutorPhase4Flow.test.tsx`
  （Issue #165）
- Event/State/Schedule 原子性と schedule rebuild:
  `backend/app/services/review_schedule_rebuilder.py`
  / `backend/tests/test_review_schedule_rebuilder.py`
  / `scripts/rebuild_review_schedules.py`
  （Issue #166）
- 最小API: `backend/app/api/tutor.py` / `backend/app/services/tutor_service.py`
  / `backend/tests/test_tutor_api.py` / `backend/tests/test_tutor_service.py`
- 抽出: `backend/app/services/extraction_service.py`
  / `backend/app/services/extractors.py`
  / `backend/app/services/openai_extractor.py`
  / `backend/tests/test_extraction_service.py`
  / `backend/tests/test_openai_extractor.py`
- 正規化: `backend/app/domain/candidate_normalization.py`
  / `backend/tests/test_candidate_normalization.py`
- 抽出・採否: `backend/app/services/candidate_service.py`
  / `backend/tests/test_candidate_service.py` / `backend/tests/test_candidate_api.py`
- Frontend Candidate UI: `frontend/src/hooks/useTutorSourceCandidates.ts`
  / `frontend/src/components/TutorCandidateList.tsx`
  / `frontend/src/test/TutorSourceDetail.test.tsx`
- 抽出品質: `backend/app/evaluation/` / `scripts/evaluate_tutor_extraction.py`
  / `backend/tests/test_extraction_quality.py`
  / `docs/tutor_extraction_quality.md`
- Phase 2 vertical slice: `backend/tests/test_tutor_phase2_vertical_slice.py`
  / `frontend/src/test/TutorPhase2Flow.test.tsx`
- Phase 3 vertical slice: `backend/tests/test_tutor_phase3_vertical_slice.py`
  / `frontend/src/test/TutorPhase3Flow.test.tsx`
- Phase 4 vertical slice: `backend/tests/test_tutor_phase4_vertical_slice.py`
  / `frontend/src/test/TutorPhase4Flow.test.tsx`
- Exercise 契約: `backend/app/domain/exercise.py`
  / `backend/tests/test_exercise.py`
- Exercise 生成: `backend/app/domain/exercise_generation.py`
  / `backend/tests/test_exercise_generation.py`
  / `backend/tests/test_exercise_cloze.py`
- conjugation adapter: `backend/app/domain/conjugation_adapter.py`
  / `backend/tests/test_exercise_conjugation_adapter.py`
- Exercise 採点: `backend/app/domain/exercise_evaluation.py`
  / `backend/app/services/exercise_service.py`
  / `backend/tests/test_exercise_evaluation.py`
  / `backend/tests/test_exercise_service.py`
  / `backend/tests/test_exercise_api.py`
- Practice Session: `backend/app/domain/practice_session.py`
  / `backend/app/services/practice_session_service.py`
  / `backend/tests/test_practice_session.py`
  / `backend/tests/test_practice_session_service.py`
  / `backend/tests/test_practice_session_api.py`
- Practice Session UI: `frontend/src/hooks/usePracticeSession.ts`
  / `frontend/src/components/PracticeSessionFlow.tsx`
  / `frontend/src/components/PracticeExerciseCard.tsx`
  / `frontend/src/test/PracticeSessionFlow.test.tsx`
  / `frontend/src/test/PracticeExerciseCard.test.tsx`

## 目指す学習ループ

```text
French source
  -> 学習候補を抽出
  -> LearningItemとして正規化
  -> 問題・説明・TTS等で学習
  -> LearningEventを記録
  -> LearnerStateを更新
  -> ReviewScheduleに従い再出題
  -> 定着後は頻度を下げ、新規項目へ進む
```

## 責務

HTTP から永続化までの層は次の一方向に依存する。下位層は上位層を知らない。

```text
api
  -> application/service
     -> domain
     -> repository interface
        -> SQLite persistence
```

| 層 | 置き場所 | やってよいこと | やってはいけないこと |
|----|----------|----------------|----------------------|
| api | `backend/app/api/tutor.py` | パス・status・request/response schema | domain ルール、SQL、repository の直接利用 |
| application/service | `backend/app/services/` | ユースケースの組み立て、存在確認、例外の意味づけ | ORM / SQLAlchemy の import |
| domain | `backend/app/domain/` | モデル不変条件、状態更新、間隔算出 | FastAPI / SQLAlchemy / HTTP |
| repository interface | `backend/app/repositories/protocols.py` | 永続化操作の契約 | 実装詳細 |
| SQLite persistence | `backend/app/persistence/` と `repositories/sqlite.py` | schema・TX・SQL | 学習ルールの再実装 |

## データフロー

Phase 0 で成立させる学習データの流れ。

```text
SourceDocument
  -> LLM extraction
  -> LearningItemCandidate
  -> validation / normalization / user review
  -> LearningItem
  -> LearningEvent
  -> LearnerState
  -> ReviewSchedule
```

1. `SourceDocument` を手入力で保存する（どこで出会ったか）
2. その Source に紐づく `LearningItem` を固定 fixture として登録する（何を覚えるか）
3. review を記録すると `LearningEvent` が append される
4. 同じ review から `LearnerState` が更新される
5. 同じ review から `ReviewSchedule` が更新される
6. `list_due(now)` が `due_at <= now` かつ active な項目だけを返す

Phase 0 の fixture は LLM で抽出しない。例:

- Source: `Je me suis rendu compte qu'il fallait changer de stratégie.`
- LearningItem: `se rendre compte de`（type: `expression`、meaning: `〜に気づく`）

## 中核モデル

| モデル | 責務 | 性質 |
|--------|------|------|
| `SourceDocument` | ユーザーが触れた素材そのもの（原文） | 追加のみ。原文は書き換えない |
| `LearningItemCandidate` | LLM が提案した学習候補 | 未確定。`candidate` / `accepted` / `rejected` |
| `LearningItem` | 素材から抽出・正規化した「学習対象」 | 更新される（status等） |
| `LearningEvent` | 学習者の行動の記録 | append-only（`frozen=True`） |
| `LearnerState` | LearningEventを集約した現在の習熟状態 | 上書き更新される |
| `ReviewSchedule` | 次にいつ復習するか（Item × SkillDirection） | 上書き更新される |

補助モデル: `SourceRef`（LearningItem → SourceDocument の参照）、
`EvidenceSpan`（原文中の根拠位置）、`MasteryStats`（習熟度の集計値）。

## 設計判断

### 1. SourceDocument と LearningItem を統合しない

**Source は「どこで出会ったか」、LearningItem は「何を覚えるか」。**
粒度もライフサイクルも異なる。

- 1つのSourceから複数のLearningItemが生まれる（1対多）
- 同じ表現（例: `il s'agit de`）が複数のSourceに現れても、
  LearningItemは1件に正規化し、出典を `source_refs` に積み増す（多対多）
- Sourceを削除・非表示にしても、すでに学習中のLearningItemの習熟は失われない
- Sourceは原文の保存が責務であり、意味・難易度・学習状態を持たない

このため `LearningItem.source_refs: list[SourceRef]` という参照リストを持ち、
Sourceの本文をLearningItem側にコピーしない。

### 1.1 LearningItem と LearningItemCandidate を同一モデルにしない

**Candidate は「LLMが提案した学習候補」、LearningItem は「覚える対象として確定した項目」。**

Phase 2 の中心原則:

```text
SourceDocument
  -> LLM extraction
  -> LearningItemCandidate
  -> validation / normalization / user review
  -> LearningItem
```

- Candidate は 1つの Source に紐づく（`source_document_id` は必須）
- LearningItem は複数 Source から再発見されうる（`source_refs`）
- Candidate の status は `candidate` / `accepted` / `rejected`
- LearningItem の status は `active` / `suspended` / `mastered`
- LLM raw response 全文は DB に必須保存しない。debug 用に
  `metadata` へ provider / model / request id 等を最小限載せられる
- 原文断片は `evidence_span.start` / `end` から Source 本文をスライスして再構成する
  （`read_source_evidence`）。後続 service が範囲外を検出できる

`accepted` / `rejected` は終端状態であり、そこからの再遷移は許可しない
（`apply_candidate_status`）。

### 2. LearningEvent と LearnerState を分ける

**Event は履歴、State は現在値。State は event から更新される。**

分離する理由:

1. **履歴は書き換えない** — 「3日前にproductionで誤答した」という事実は、
   その後正解しても消えない。`LearningEvent` は `frozen=True` とし、
   訂正が必要な場合は新しいイベントを追記する（append-only）。
2. **問い合わせコスト** — 「今この項目をどれだけ習得しているか」を
   毎回全イベントの再走査で求めるのは非効率。`LearnerState` は集約結果の
   キャッシュとして機能する。
3. **アルゴリズム変更への耐性** — 習熟度の計算式を変えても、
   `LearningEvent` が残っていれば `LearnerState` を再計算できる。
   逆に状態だけ持っていると、過去に遡った再計算ができない。
4. **将来の分析** — 誤答パターン・時間帯・応答時間の分析は履歴がないとできない。

`LearnerState` は `LearningEvent` から導出可能な値のみを持つ、という原則を保つ。

### 3. 「知っている」を単一booleanにしない

`LearnerState` は `MasteryStats` を継承し、集計値（`attempt_count` /
`correct_count` / `consecutive_correct` / `mastery_score` 等）を持つ。

さらに `by_direction: dict[SkillDirection, MasteryStats]` を用意し、
`recognition`（見て分かる）と `production`（自力で produce できる）を
別々に追跡する。Phase 4（Issue #161）で `apply_review_event` が
ExerciseType の deterministic mapping から direction を決め、
全体集計と該当 direction 集計の双方を更新する。
Client が送った `metadata.skill_direction` は監査用であり、集計の
source of truth にはしない。

### 4. 時刻はtimezone-aware（内部表現はUTC）

すべての日時フィールドは `UtcDatetime` 型を使う。

```python
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(UTC))]
```

- naiveな `datetime` は `ValidationError` として弾く
- aware な値は入力タイムゾーンを問わずUTCへ正規化して保持する
- 現在時刻は `utcnow()`（= `datetime.now(UTC)`）を使い、`datetime.utcnow()` は使わない

理由: 学習履歴と復習予定は日を跨いで比較・ソートされる。ローカル時刻と
UTCが混在すると「今日の復習」の判定が壊れる。表示用のタイムゾーン変換は
UI層の責務とし、domain層はUTCで一貫させる。

この方針は `tests/test_tutor_domain.py` の
`test_*_rejects_naive_*` / `test_*_normalizes_*_to_utc` で検証している。

### 5. ID採番は永続化実装と疎結合にする

`new_id()`（UUID4文字列）を domain層で提供し、各モデルの `id` の
`default_factory` に使う。

- DBのauto incrementに依存しないため、永続化前のオブジェクトもIDを持てる
- 将来DBを導入してもこのIDをそのまま主キーにできる
- テストでSourceとLearningItemを紐付ける際に、DBなしで参照が成立する

### 6. LLMを真実のデータベースにしない

詳細は「LLM境界」を参照。Phase 0 では LLM を使わず、
`evidence_span` / `confidence` は `None` のままでよい。

## 不変条件（バリデーション）

| モデル | 不変条件 |
|--------|----------|
| `SourceDocument` | `title` / `content` は空文字不可 |
| `EvidenceSpan` | `start >= 0` かつ `end > start` |
| `SourceRef` | `confidence` は 0.0〜1.0 |
| `LearningItem` | `canonical_form` / `meaning_ja` は空文字不可 |
| `LearningItemCandidate` | `canonical_form` / `meaning_ja` / `extraction_version` は空文字不可 |
| `LearningItemCandidate` | `confidence` は 0.0〜1.0。未知の `item_type` / `status` は reject |
| `LearningItemCandidate` | `candidate` からのみ `accepted` / `rejected` へ遷移できる |
| `LearningEvent` | `response_time_ms >= 0`、生成後は変更不可 |
| `MasteryStats` | `attempt_count == correct_count + incorrect_count` |
| `MasteryStats` | `consecutive_correct <= correct_count` |
| `MasteryStats` | `mastery_score` は 0.0〜1.0 |
| `MasteryStats` | `attempt_count == 0` ⇔ `last_reviewed_at is None` |
| `ReviewSchedule` | `interval_days >= 0`、`review_count` / `lapse_count` は非負 |
| `ReviewSchedule` | 同一 Item + 同一 `skill_direction` に 1 件 |

enum相当の値はすべて `Literal` で定義しており、未知の値は
`ValidationError` になる（`item_type` / `status` / `result` / `exercise_type` 等）。

`interval_days` は `float`。数分後の再学習ステップなど1日未満の間隔を
表現できるようにするため。

## 既存クイズとの関係

現行の動詞・名詞・冠詞クイズは当面、独立した既存 Exercise layer として維持する。

- Phase 0 では既存 quiz 結果を自動で `LearningEvent` へ変換しない
- 既存の動詞・名詞データは Tutor DB へ移行しない（`conjugation.py` / `noun.py` のまま）
- Phase 3 で `LearningItem -> Exercise` 接続を行う際に、既存 quiz 基盤を再利用する

`ExerciseType` には既存モード（`verb_conjugation` / `noun_gender` /
`noun_article`）を含めてある。これは将来の接続のための型であり、
Phase 0 の API が quiz 回答を Tutor 履歴へ書き込むことはない。

Phase 3 では Tutor layer から既存 quiz へ委譲する境界だけを定義し、
既存クイズの全面刷新はしない。`noun_gender` / `noun_article` は
既存クイズ専用のまま LearningItem から新規生成しない。
`verb_conjugation` は lemma が `CONJUGATIONS` にあり、かつ
`metadata.tense` が既存実装の対応時制と一致する conjugation item に
限って既存実装へ委譲できる。tense 欠落を présent とみなさない。

Phase 0時点では `backend/app/domain/conjugation.py` /
`backend/app/domain/noun.py` に一切変更を加えていない（破壊的変更なし）。

## LLM境界

- Phase 0 は LLM 非依存。Source / LearningItem は手入力またはテスト fixture で与える
- Phase 1 も LLM 非依存。ユーザーが貼り付けた本文を SourceDocument として保存・表示するだけ
- Phase 2 で Source から LearningItem 候補（`LearningItemCandidate`）を生成する
- LLM 生成結果は正規化・ validation 後に domain へ入れる。出力をそのまま正解データにしない
- OpenAI SDK は `openai_extractor.py` に閉じる。domain / ExtractionService は
  `LearningItemExtractor` Protocol にだけ依存する
- Issue #132 は抽出まで。Issue #133 で Candidate の evidence 検証・正規化・
  重複統合を行う。永続化と採否 API は #134（`CandidateService`）、Frontend は #135。
  抽出品質の固定 fixture と評価ハーネスは #136。Phase 2 の vertical slice と
  Exit Criteria の固定は #137

`SourceRef` は Phase 2 に備えて `evidence_span` と `confidence` を
optional で持てる。Phase 0 ではどちらも `None` のままでよい。

## 永続化層（Issue #109）

Tutor機能の可変ユーザーデータだけを永続化する。
既存の動詞・名詞正解データ（`conjugation.py` / `noun.py`）はコード内管理のままにする。

### 採用した実装

**SQLAlchemy 2.x（同期）+ SQLite + 明示的 Repository。**

| 候補 | 判断 |
|------|------|
| SQLAlchemy 2.x + SQLite | 採用。JSON列・FK・将来の PostgreSQL 切替を dialect 差ごと吸収できる |
| Python 標準 `sqlite3` | 不採用。クエリ拡張と PostgreSQL 移行時に SQL を二重管理することになる |
| Alembic | Phase 0 では未導入。初期スキーマが1版のみのため |

`architecture.md` は将来の PostgreSQL 移行で Alembic を使う想定を残している。
Phase 0 ではテーブルが domain モデルと 1:1 で、破壊的変更もまだない。
Alembic の env / revision 一式を今足すより、`schema_migrations` で現行バージョンを
記録する方が小さい。連続した ALTER または PostgreSQL 移行が必要になった時点で
Alembic へ移す。

### Repository 境界

service / domain は SQLite や ORM を直接 import しない。
`backend/app/repositories/protocols.py` が Phase 0 で必要な操作だけを定義する。

| Repository | 操作 | 備考 |
|------------|------|------|
| `SourceDocumentRepository` | create / get / list | 削除なし |
| `LearningItemRepository` | create / get / list | 削除なし |
| `LearningItemCandidateRepository` | create / create_many / get / list_by_source / update_status | 削除なし。存在しない Source は拒否。create_many は同一 TX |
| `CandidatePromotionRepository` | persist_accept | Candidate accepted 化と LearningItem create/update を同一 TX |
| `LearningEventRepository` | append / list_by_item | append-only。`occurred_at`, `id` 順 |
| `LearnerStateRepository` | get / upsert | LearningItem につき1件（PK） |
| `LearningProgressRepository` | append_event_and_upsert_state / append_event_upsert_state_and_schedule | 回答記録時は event / state / 該当 direction の schedule を同一トランザクション |
| `ReviewScheduleRepository` | get(item_id, direction) / upsert / list_for_item / list_due / replace_for_item | Item × direction につき1件（複合PK）。rebuild は Item 単位で全置換 |

SQLite 実装の入口は `TutorSqliteStore`。
接続先は `TUTOR_DATABASE_URL`、未指定時は `backend/data/tutor.db`。
テストは `TutorSqliteStore.in_memory()` または temporary file URL を使う。

### データ整合性

- `LearningEvent` / `LearnerState` / `ReviewSchedule` は存在する
  `LearningItem` を参照する（FK + repository 側の存在チェック）
- `LearningItemCandidate` は存在する `SourceDocument` を参照する
  （FK + repository 側の存在チェック）
- `LearnerState` は `learning_item_id` を主キーにし、1件に制限する
- `ReviewSchedule` は `(learning_item_id, skill_direction)` を複合主キーにし、
  同一 Item × 同一 direction に1件に制限する
- `ON DELETE RESTRICT` により、履歴がある LearningItem を SQL から消しても失敗する
- repository に `delete` を置かない（履歴消失を安易に許可しない）
- 日時は timezone-aware のみ受け付け、UTC の ISO 8601
  （`YYYY-MM-DDTHH:MM:SS.ffffff+00:00`）で保存する。
  この形式なら文字列比較が時系列順と一致し、`due_at <= now` を SQL で判定できる

### トランザクションの保証範囲

`TutorService.record_review` は回答1件について次を **同一トランザクション** で書き込む（Issue #166）。

```text
LearningEvent append
 + LearnerState upsert
 + 該当 skill_direction の ReviewSchedule upsert
```

- state 書き込み失敗 → event / schedule も残らない
  （`test_record_review_state_failure_rolls_back_event_and_schedule`）
- schedule 書き込み失敗 → event / state も commit されない
  （`test_record_review_schedule_failure_rolls_back_event_and_state` /
  `test_schedule_write_failure_rolls_back_event_and_state`）
- duplicate event ID → 3者とも変更なし
  （`test_record_review_duplicate_event_id_raises_conflict`）

`LearningStateService.record_event` は従来どおり event / state だけの
同一 TX を提供する（schedule を持たない履歴修復や direction 不明 event 用）。
回答記録の正規経路は `record_review` である。

Phase 0 では schedule を別 TX としており、失敗時に event/state だけが残る
状態を許容していた。Phase 4 では due queue がユーザー体験の入口になるため、
新規回答でこの不整合を新たに作らない。既存 / legacy DB の欠損は
`ReviewScheduleRebuilder` が LearningEvent 履歴から再構築する。

### schema versioning

`schema_migrations` テーブルが適用済み version を保持する。

1. version 0（未初期化）: `create_all` で現行スキーマを作り version 3 を記録する
2. version < 現行: `UPGRADE_STEPS` の upgrade 関数を順に適用する
3. version > 現行: `SchemaVersionError`（新しいDBを古いコードで開いた）

現行 version は `3`。version 2 の upgrade は `learning_item_candidates`
テーブルを追加する（Issue #131）。version 3 の upgrade は
`review_schedules` を `(learning_item_id, skill_direction)` の複合主キーへ再構築し、
旧 schedule 行はコピーせず LearningEvent を direction 別に replay する
（Issue #162）。新規DBは `create_all` で version 3 を直接作る。

ローカルで生成される `*.db` は git 管理対象外（`.gitignore`）。

## 学習状態更新（Issue #110）

`LearningStateService.record_event` が LearningEvent の記録と
LearnerState の更新を行う。更新ルール自体は domain の純関数
`apply_review_event` に置き、service は存在確認と永続化を担う。

```text
LearningItem の存在確認
  -> 現在の LearnerState を取得（無ければ未学習）
  -> apply_review_event で次状態を算出
  -> LearningEvent の append と LearnerState の upsert を同一トランザクションで保存
```

同じ `LearningEvent.id` の再登録は `DuplicateEntityError` で拒否する。
トランザクションのため、拒否時に state が二重適用されることはない。

### 初期更新ルール

| フィールド | 更新 |
|------------|------|
| `attempt_count` | +1 |
| `correct_count` | correct なら +1 |
| `incorrect_count` | incorrect なら +1 |
| `consecutive_correct` | correct なら +1、incorrect なら 0 |
| `last_reviewed_at` | `event.occurred_at` |
| `mastery_score` | `correct_count / attempt_count`（未学習は 0.0） |

`mastery_score` は正答率そのもの。値域は [0.0, 1.0] で、正答で悪化せず、
誤答で改善しない。同じイベント列からは常に同じ結果になる。

`exercise_type` は LearningEvent に必ず残す。Phase 4（Issue #161）では
このフィールドから SkillDirection を決定し、`by_direction` を更新する。

### direction 別集計（Issue #161）

```text
LearningEvent
  -> ExerciseType から SkillDirection を決定
  -> LearnerState 全体を更新
  -> LearnerState.by_direction[direction] を更新
```

source of truth は `SKILL_DIRECTION_BY_EXERCISE_TYPE`
（`backend/app/domain/tutor.py`）。Issue #145 の
`skill_direction_for` と同じ対応を domain に置き、`exercise` 層へ
依存しない。`LearningEvent.metadata.skill_direction` は追跡用であり、
集計ロジックは Client 由来 metadata を見ない。

1イベントにつき、全体集計と該当 direction 集計が1回だけ更新される。
recognition の正答は production の mastery を上げず、production の誤答は
recognition の consecutive_correct を壊さない。

初期 mastery は全体と同じ説明可能な正答率ベース。FSRS 等は行わない。

Phase 3 以前 / legacy event:

- `exercise_type` から direction を決定できる event は direction 集計へ含める
- mapping に無い exercise_type は全体集計だけ更新し、direction には
  metadata から推測して割り当てない

再計算: `LearningStateService.recompute_learner_state` は履歴を
`occurred_at, id` 順に replay し、全体と `by_direction` を同じ結果に戻す。

### 不整合への備え

LearnerState は LearningEvent のキャッシュである。event と state の
書き込みは同一トランザクションだが、万一 state だけ欠けた場合は
`LearningStateService.recompute_learner_state` が履歴を `occurred_at, id`
順に畳み込んで state を再構築できる。

## 復習スケジューラ（Issue #111 / #162）

`schedule_next_review(state, event, previous_schedule)` が次の
ReviewSchedule を決める。更新ルール自体は domain の純関数に置き、
service は存在確認と永続化、due 取得を担う。

Issue #162 以降、予定は LearningItem 単位ではなく
**recognition / production 別に 1 件** 持つ。回答時は当該 direction の
previous schedule と `LearnerState.by_direction[direction]` だけを入力にする。

```text
LearnerState（当該event適用後）と LearningEvent
  -> ExerciseType から SkillDirection を決定
  -> 該当 direction の previous schedule だけを取得
  -> schedule_next_review で次予定を算出
  -> ReviewSchedule を upsert
  -> list_due(now, direction optional) で due_at <= now かつ active の予定を取得
```

`datetime.now()` は domain からも service からも呼ばない。
due 算出の基準は `event.occurred_at`、due 取得の基準は引数 `now`。

### 初期スケジューリング方針

Phase 0 では SM-2 / FSRS は導入しない。日数の最適性は狙わず、
後からアルゴリズムを差し替えられる **単純・deterministic・説明可能な
baseline** にする。同じ (state, event, previous_schedule) からは
常に同じ ReviewSchedule になる。間隔テーブル自体は Issue #111 のまま。

| 条件 | interval_days |
|------|----------------|
| incorrect（lapse） | 1 |
| 連続1回正解（初回学習後を含む） | 1 |
| 連続2回正解 | 3 |
| 連続3回正解 | 7 |
| 連続4回以上 | 14（上限） |

- due_at = `event.occurred_at + interval_days`
- 連続正解が増えても interval は短くならない
- incorrect では interval を 1 日に戻し、`lapse_count` を +1
- `review_count` は previous があれば +1、なければ 1
- 連続正解は全体集計ではなく `by_direction[direction].consecutive_correct`
- `scheduler_version` は現行アルゴリズムの版（`v1-directional`）を書き込む
- 過去の schedule 履歴は残さず、当該 direction の現行予定だけを上書きする
- recognition の正答は production の interval / review_count を進めない
- production の誤答は recognition の lapse_count を増やさない

### due 取得

`ReviewScheduleRepository.list_due(now, direction=None)` /
`ReviewService.list_due(now, direction=None)`:

- `due_at <= now` の予定だけ返す
- **active な LearningItem のみ**。`suspended`（ユーザーが一時除外）と
  `mastered`（定着済み）は、予定が残っていても出題対象にしない。
  schedule 自体は消さないので、status を active に戻せば再開できる
- `direction` を指定するとその方向だけ。未指定なら両方向
- 返却順は `due_at` 昇順、同じ due_at なら `learning_item_id`、
  `skill_direction` 昇順
- 同一 Item の recognition と production が両方 due なら 2 件返す
- HTTP の direction-aware queue は `GET /api/tutor/reviews/queue`
  （Issue #163）。Phase 0 の `GET /api/tutor/reviews/due` は維持する

### 将来拡張への備え

- `scheduler_version` でアルゴリズムを識別する
- 間隔計算（domain）と due query（repository）を分離している
- 後続で SM-2 / FSRS 等と比較・移行できる
- 過去 schedule を再計算して履歴を書き換える設計にはしない
- 欠けた schedule は LearningEvent 履歴から
  `rebuild_directional_schedules` で再構築できる

## 最小 API（Issue #112）

Phase 0 の domain / persistence / learning state / review scheduler を、
Frontend や LLM ingestion から利用できる最小 HTTP API として公開する。
UI・認証・LLM抽出は含めない。synthetic な SourceDocument / LearningItem を
登録し、学習イベント記録と due review 取得ができることに限定する。

router（`app/api/tutor.py`）は request/response schema と HTTP status 変換だけを持つ。
repository へは直接アクセスせず、`TutorService` が既存 service を組み合わせる。

```text
POST /api/tutor/items/{item_id}/reviews
  -> LearningEvent append
  -> LearnerState update
  -> ReviewSchedule update
```

### エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| POST | `/api/tutor/sources` | 手入力テキストの SourceDocument を作成（201） |
| GET | `/api/tutor/sources` | 保存済み Source の一覧。`created_at` 降順、同一時刻は `id` 昇順 |
| GET | `/api/tutor/sources/{source_id}` | 1件取得 |
| POST | `/api/tutor/items` | 手入力の LearningItem を作成（201） |
| GET | `/api/tutor/items/{item_id}` | item と現在の LearnerState / ReviewSchedule |
| POST | `/api/tutor/items/{item_id}/reviews` | 復習イベントを記録（201） |
| GET | `/api/tutor/reviews/due` | 現在 due の active LearningItem |
| GET | `/api/tutor/reviews/queue` | direction-aware な due review queue（Issue #163） |
| POST | `/api/tutor/review/sessions` | due queue から Review Practice Session を生成（Issue #164） |

`GET /api/tutor/reviews/due` は任意時刻を HTTP query から受け取らない。
due 判定の基準はサーバー時刻（`utcnow`）。テストでは `TutorService` の
`clock` 注入、または過去の `occurred_at` で due を作る。
`GET /api/tutor/reviews/queue` も任意時刻 query は持たない。Phase 0 の
due 一覧契約は維持し、queue は別 endpoint とする。

### Source 一覧（Issue #121）

`GET /api/tutor/sources` は履歴画面向けに、保存済み Source の要約だけを返す。
全文が必要な場合は既存の `GET /api/tutor/sources/{source_id}` を使う。

| 項目 | 仕様 |
|------|------|
| 並び | `created_at` 降順。同一時刻は `id` 昇順（deterministic） |
| レスポンス | `SourceSummary`（`id` / `source_type` / `title` / `language` / `created_at` / `content_preview`） |
| `content_preview` | 本文の先頭 120 文字。全文は含めない |
| `limit` | 1〜100。未指定時は 50。不正値は 422 |
| 0件 | 200 + `[]` |

`limit` は高度な pagination ではなく、無制限取得を固定仕様にしないための上限である。
router は SQL を扱わず、`TutorService.list_sources` 経由で Repository の `list` を使う。

### review の `occurred_at`

- 指定した場合: その時刻を LearningEvent の発生時刻とする（timezone-aware 必須）
- 未指定の場合: サーバーの現在時刻（UTC）を使う

### 不正な Source 参照

LearningItem の `source_refs` は空でよい（出典なしの synthetic item）。
`source_document_id` を指定した場合、その SourceDocument が存在しなければ
**422** で拒否する。存在しない出典へのぶら下がり参照は作らない。

### HTTP status

| 状況 | status |
|------|--------|
| Source / Item / Event の作成成功 | 201 |
| 存在しない Source / LearningItem | 404 |
| 重複 event ID | 409 |
| 不正な `result` / `exercise_type` / 空文字 / naive datetime / 不正な `limit` | 422 |
| 存在しない Source を参照する LearningItem 作成 | 422 |

## Vertical slice 統合テスト（Issue #113）

`backend/tests/test_tutor_vertical_slice.py` が Phase 0 の学習ループを
HTTP API + SQLite で通す。clock は `TutorService` に注入し、
`datetime.now()` に依存しない。

必須 fixture:

- Source: `Je me suis rendu compte qu'il fallait changer de stratégie.`
- LearningItem: `se rendre compte de` / `expression` / `〜に気づく`

| 観点 | テスト |
|------|--------|
| Source -> Item -> Event -> State -> Schedule -> due 前後 -> 再review | `test_vertical_slice_source_to_due_to_rereview` |
| file DB 再 open 後の永続性 | 同上 |
| clock 固定による due 前後 | 同上 / `test_future_due_is_excluded_until_due_at` |
| correct 後の interval 延長 | 同上（1日 -> 3日） |
| incorrect による lapse 増加と interval 短縮 | `test_incorrect_review_increases_lapse_and_shortens_interval` |
| 複数 review 後も event history が残る | `test_multiple_reviews_preserve_event_history` |
| 存在しない item への review | `test_review_missing_item_returns_404` |
| duplicate event | `test_duplicate_event_is_rejected_without_double_apply` |
| timezone 境界 | `test_due_query_uses_timezone_boundary` |
| suspended / mastered の due 除外 | `test_suspended_and_mastered_items_are_not_due` |
| schedule 書き込み失敗時の保証 | `test_schedule_write_failure_rolls_back_event_and_state` |
| 既存 quiz / TTS 契約の回帰 | `test_existing_quiz_and_tts_contracts_are_unchanged` |

## Phase 0 Exit Criteria（Issue #107）との対応

Issue #107 の Phase 0 Exit Criteria は、synthetic な LearningItem について
次が一貫して動くこと、かつ既存クイズが回帰しないこと。

```text
LearningItem作成
 -> 学習イベント記録
 -> LearnerState更新
 -> ReviewSchedule更新
 -> due review取得
```

| Exit Criteria | 満たした実装 | 自動テスト |
|---------------|--------------|------------|
| LearningItem 作成 | `TutorService.create_item` / `POST /api/tutor/items` | `test_vertical_slice_source_to_due_to_rereview` / `test_create_and_get_learning_item` |
| 学習イベント記録 | `TutorService.record_review`（Event/State/Schedule 同一TX） | `test_vertical_slice_source_to_due_to_rereview` / `test_review_persists_event_and_updates_state_and_schedule` |
| LearnerState 更新 | domain `apply_review_event` + 同一TX upsert | `test_record_event_updates_counters_for_correct_and_incorrect` |
| ReviewSchedule 更新 | domain `schedule_next_review` + `ReviewService` | `test_schedule_after_review_sets_next_due_for_first_review` |
| due review 取得 | `ReviewScheduleRepository.list_due` / `GET /api/tutor/reviews/due` | `test_vertical_slice_source_to_due_to_rereview` / `test_list_due_uses_injected_now_not_wall_clock` |
| 既存動詞・名詞クイズの回帰なし | quiz API は Tutor DB を使わない | `test_existing_quiz_and_tts_contracts_are_unchanged` / `tests/test_api.py` / `tests/test_nouns.py` |
| 永続化境界 | Repository Protocol + SQLite | `tests/test_tutor_persistence.py` |
| LLM 非依存 | Phase 0 の service / API に LLM 呼び出しなし | 実装上 import せず、本ドキュメントの LLM境界で明記 |

Phase 1 へ進む前提は、上記が `bash scripts/quality-check.sh` で
継続して通ることである。

## Phase 1 — Text Source Ingestion（Issue #121〜#125）

Phase 1 のゴールは LLM による教材化ではなく、**実際のフランス語本文を
アプリへ持ち込み、永続化し、あとから見つけて読み返せること**である。

Frontend は `TutorFlow` が一覧 / 追加 / 詳細を切り替え、
Backend は既存の Source API をそのまま入力基盤として使う。

```text
manual French text
  -> SourceDocument
  -> SQLite persistence
  -> source list
  -> source detail
```

推奨 fixture:

```text
Title: Article test
Content: Je me suis rendu compte qu'il fallait changer de stratégie.
Note: se rendre compte が気になった
```

Phase 1 ではこの文から LearningItem を抽出しない。

### Phase 1 で成立したこと

| 操作 | 実装 | 自動テスト |
|------|------|------------|
| フランス語本文の手動貼り付け | `TutorSourceForm` | `TutorPhase1Flow.test.tsx` / `TutorSourceForm.test.tsx` |
| title / optional note とともに保存 | `POST /api/tutor/sources`（`metadata.note`） | `test_phase1_text_ingestion_vertical_slice` |
| 保存済み Source 一覧 | `GET /api/tutor/sources` / `TutorSourceList` | 同上 / `TutorSourceList.test.tsx` |
| Source 詳細で原文全文を読む | `GET /api/tutor/sources/{source_id}` / `TutorSourceDetail` | 同上 / `TutorSourceDetail.test.tsx` |
| アプリ / DB 再 open 後も残る | SQLite file DB + 一覧の再 fetch | `test_phase1_text_ingestion_vertical_slice` / `TutorPhase1Flow.test.tsx` |
| empty / loading / error / 404 | list / detail hooks | `TutorPhase1Flow.test.tsx` / 各コンポーネントテスト |
| 一覧順が安定 | `created_at` 降順、同一時刻は `id` 昇順 | `test_phase1_newer_source_appears_first` / `test_phase1_list_order_is_stable_for_same_created_at` |
| 404 / validation | 空 title/content、未知の source_type、不正 limit | `test_phase1_missing_source_returns_404` / `test_phase1_validation_errors` |

### Phase 1 ではまだ行わないこと

- Source から LearningItem を生成しない
- LLM を呼ばない
- URL / PDF / YouTube 等を自動取得しない
- Source 内容を自動要約しない
- Source の編集・削除を提供しない

`SourceType` は `manual_text` のみ。`CreateSourceRequest` は `source_type` を
受け取らず、作成時は常に手入力テキストになる。

### Phase 2 への引き継ぎ

Phase 2 は保存済み SourceDocument を入力として、LearningItem 候補抽出を行う。
Phase 1 の UI / API はその入力基盤として維持する。抽出結果は正規化・
validation 後に domain へ入れ、LLM 出力をそのまま正解データにしない。

Issue #131 で `LearningItemCandidate` の domain model と SQLite 永続化を追加した。
Issue #132 で SourceDocument から Candidate を得る Extraction Service を追加した。
Issue #133 で evidence 検証・正規化・同一 Source 内の重複統合を追加した。
Issue #134 で抽出結果の保存と accept / reject API を追加した。Frontend は #135。
Issue #136 で固定 fixture と deterministic な抽出品質ハーネスを追加した。
Issue #137 で Source → Candidate → LearningItem を一本の vertical slice として
閉じ、Phase 2 Exit Criteria と Phase 3 への引継ぎをこのドキュメントに固定した。

## Phase 2 Candidate 永続化（Issue #131）

| 操作 | 実装 | 自動テスト |
|------|------|------------|
| Candidate 作成 | `LearningItemCandidate` + `LearningItemCandidateRepository.create` | `test_learning_item_candidate_create_and_get_are_persisted` |
| 不正 enum / confidence / 空文字 | domain validation | `test_candidate_rejects_*` |
| 存在しない Source 参照 | repository の存在チェック | `test_candidate_create_requires_existing_source` |
| Source 単位一覧 | `list_by_source` | `test_learning_item_candidate_list_by_source` |
| status 更新 | `apply_candidate_status` + `update_status` | `test_candidate_status_update_is_persisted` |
| DB 再 open | file SQLite | `test_candidate_survives_reopen_without_affecting_existing_schema` |
| schema 1 → 2 | `UPGRADE_STEPS` | `test_schema_upgrades_from_v1_and_preserves_existing_rows` |

## Phase 2 LLM Extraction（Issue #132）

保存済み `SourceDocument` を入力とし、語彙・表現・文法・活用の学習候補を
structured output で得る。LLM は候補生成器であり、出力を `LearningItem` に
直接保存しない。

```text
SourceDocument
  -> LearningItemExtractor (Protocol)
       OpenAILearningItemExtractor | fake
  -> ExtractionLlmOutput (Pydantic schema)
  -> ExtractionService
  -> LearningItemCandidate (status=candidate)
```

| 関心 | 実装 | 備考 |
|------|------|------|
| prompt / version | `extraction_prompt.py` の `EXTRACTION_VERSION` | Candidate.extraction_version と metadata.prompt_version に載せる |
| structured schema | `extraction_schema.py` | 未知 enum・必須欠落・confidence 範囲・span 形状・20件上限を reject |
| provider 境界 | `LearningItemExtractor` | OpenAI SDK を service/domain へ拡散させない |
| OpenAI 実装 | `OpenAILearningItemExtractor` | `chat.completions.parse`。API key は呼び出し時に読む |
| ユースケース | `ExtractionService.extract` | Candidate へ写す。LearningItem は作らない |
| エラー分類 | `ExtractionConfigError` / `ExtractionTransientError` / `ExtractionInvalidResponseError` | 一時障害だけ最大3回 retry。validation 失敗は retry しない |

テストは fake extractor と mocked OpenAI client で行い、`OPENAI_API_KEY` なしで通る。
evidence 検証・正規化・重複統合は #133、Candidate 保存と採否 API は #134。

## Phase 2 Candidate normalization（Issue #133）

LLM から得た構造化候補を、そのまま永続化・提示せず、Source 本文との整合性
検証、表記正規化、同一 Source 内の重複統合を行う。LLM を真実のデータベース
にせず、**出力の後ろに deterministic な防波堤を置く**。

```text
SourceDocument + raw LearningItemCandidate[]
  -> evidence span 検証（本文から根拠を再構成）
  -> canonical_form / meaning_ja の正規化
  -> invalid を理由付きで除外
  -> structured key で同一 Source 内の重複を統合
  -> LearningItemCandidate[] + CandidateExclusion[]
```

実装は `backend/app/domain/candidate_normalization.py`。
`ExtractionService.extract` が写し終わった Candidate に対して呼ぶ。
embedding / vector DB には依存しない。

### whitespace / Unicode

| 対象 | 方針 |
|------|------|
| evidence オフセット | Python の Unicode コードポイント（`len` / スライス）。バイトでも grapheme でもない |
| span 検証対象 | 保存済み `SourceDocument.content`。検証前に本文を NFC しない |
| 根拠断片 | LLM の text を信じず `read_source_evidence` で `content[start:end]` から再構成 |
| 受理条件 | `0 <= start < end <= len(content)`。再構成結果が空 / whitespace のみは除外 |
| canonical_form | NFC、前後空白除去、連続空白の圧縮、囲み引用符の除去。大文字小文字は維持 |
| meaning_ja | NFC と空白正規化 |
| 重複キー | `candidate-norm-v1:{item_type}:{正規化形.casefold()}` |

### item type ごとの正規化

| item_type | 規則 |
|-----------|------|
| 共通 | 空白・NFC・囲み引用符。フランス語としての正誤は LLM だけで最終確定しない |
| vocabulary | 文末記号、またはトークン数が 3 を超える文脈付き断片は除外（`pomme de terre` は許容） |
| expression | 再利用可能な表記へ空白・引用符を揃える。活用形から原形への変換はしない |
| grammar | 共通規則のみ |
| conjugation | 正規化後の canonical_form を `metadata.lemma` に載せる。tense / mood は許可リスト内のときだけ載せ、未知の自由文字列は捨てる。未抽出なら載せない |

### 重複統合と既存 LearningItem

- 同一 Source 内は `item_normalization_key` が一致するものを 1 件に統合する
- 残すのは confidence が高い方。同点なら先に現れた方（index が小さい方）
- 異なる item_type は同じ表記でも統合しない
- 既存 LearningItem との比較には同じ `item_normalization_key` を使う
- accept 時に source_ref を足す処理は `CandidateService.accept`（Issue #134）

### invalid の扱い

スキーマ段階（未知 enum・必須欠落・confidence 範囲外・span 形状）は
Extractor / Pydantic が応答全体を reject する。パイプラインは Candidate 単位で:

| 理由 | 内容 |
|------|------|
| `evidence_span_out_of_range` | Source 本文の範囲外 |
| `evidence_span_empty` | 再構成結果が空または whitespace のみ |
| `empty_canonical_form` | 正規化後に空 |
| `empty_meaning_ja` | 正規化後に空 |
| `vocabulary_context_fragment` | 語彙なのに文脈付き断片 |
| `duplicate` | 同一 Source 内の structured key 重複 |

除外は `CandidateExclusion` に残し、黙って捨てない。
`ExtractionResult.exclusions` からテスト・debug できる。

| 観点 | 自動テスト |
|------|------------|
| 正しい span は残る | `test_valid_span_is_kept` |
| Source 外 span は落ちる | `test_span_outside_source_is_excluded` |
| whitespace のみの span は落ちる | `test_whitespace_only_span_is_excluded` |
| 同一 candidate の複数件は 1 件に統合 | `test_duplicate_candidates_are_merged_to_one` |
| 大文字小文字 / 前後空白で爆発しない | `test_case_and_whitespace_differences_do_not_duplicate` |
| 異なる item_type は統合しない | `test_different_item_types_are_not_merged` |
| 実行ごとに結果が変わらない | `test_normalization_is_deterministic` |
| 除外理由を確認できる | `test_exclusion_reasons_are_inspectable` |
| 既存 LearningItem と比較できる key | `test_normalization_key_matches_existing_learning_item` |
| embedding 非依存 | `test_module_does_not_depend_on_embeddings` |
| fake LLM 経由の抽出 | `test_extract_excludes_out_of_range_span_and_keeps_valid` / `test_extract_merges_duplicates_from_fake_llm_response` |

## Phase 2 Candidate 抽出・採否 API（Issue #134）

保存済み Source に対して抽出を実行し、Candidate の一覧・採用・却下を行う。
LLM 出力は必ず Candidate を経由し、accept したときだけ LearningItem になる。

```text
POST /api/tutor/sources/{source_id}/candidates/extract
GET  /api/tutor/sources/{source_id}/candidates
POST /api/tutor/candidates/{candidate_id}/accept
POST /api/tutor/candidates/{candidate_id}/reject
```

```text
Source 取得
  -> ExtractionService（validation / normalization / dedup）
  -> 既存 Candidate と同じ normalization key は保存しない
  -> 新規 Candidate のみ同一 TX で保存
```

再抽出では accepted / rejected を `candidate` に戻さない。rejected の履歴は残し、
同じ key が即座に未判定へ戻ることはない。provider 障害時は既存行を変更しない。

accept:

- `candidate` → LearningItem を新規作成、または `item_normalization_key` が一致する
  既存 Item へ SourceRef を追加。同じ `source_document_id` の二重追加はしない
- 再 accept は冪等
- `rejected` からの accept は 409
- evidence が Source 本文と整合しない Candidate は 422
- LearningItem 書き込みと Candidate accepted 化は同一トランザクション

reject:

- status を `rejected` にする。LearningItem は作らない
- 再 reject は冪等
- `accepted` からの reject は 409

HTTP エラー:

| 状況 | status |
|------|--------|
| Source / Candidate 不存在 | 404 |
| 不正な status 遷移 | 409 |
| invalid Candidate の accept | 422 |
| API key 未設定 / LLM 一時障害 | 503 |
| LLM 応答不正 | 502 |

router は HTTP 変換のみ。LLM / SQL / domain rule は `CandidateService` に置く。
API レスポンスに provider の生応答や Candidate.metadata は載せない。
`evidence_text` は Backend が Source 本文から再構成する。

| 観点 | 自動テスト |
|------|------------|
| extract で Candidate が保存される | `test_extract_saves_candidates` / `test_extract_saves_candidates_and_hides_provider_payload` |
| Source 単位一覧 | `test_list_for_source_includes_status_and_evidence_text` |
| accept で LearningItem が作られる | `test_accept_creates_learning_item_with_source_ref_and_evidence` |
| 既存 Item 一致時に重複作成されない | `test_accept_merges_into_existing_learning_item` |
| reject で LearningItem が作られない | `test_reject_does_not_create_learning_item` |
| 再 extract で重複爆発しない | `test_reextract_does_not_duplicate_pending_candidates` |
| rejected を復活させない | `test_reextract_does_not_revive_rejected` |
| provider error で既存が壊れない | `test_provider_error_leaves_existing_candidates` |
| transaction failure で中途半端にならない | `test_item_write_failure_leaves_candidate_pending` |
| 状態遷移 | `test_reaccept_is_idempotent` / `test_accept_rejected_is_forbidden` |

Frontend は #135 で Source 詳細から抽出・確認・採否できるようにした。
抽出品質の固定評価は #136（`docs/tutor_extraction_quality.md`）。

## Phase 2 Candidate レビュー UI（Issue #135）

保存済み Source の詳細画面から、LLM 抽出の Candidate を確認して採用・却下する。
LLM の生応答や metadata は通常 UI に出さない。evidence は Backend が再構成した
`evidence_text` を引用表示する。

```text
Source 詳細
  -> 「学習候補を抽出」
  -> loading（多重実行しない）
  -> Candidate 一覧
  -> 内容と原文根拠を確認
  -> 採用 / 却下
  -> status 更新（失敗時は元の status のまま）
```

| 関心 | 実装 |
|------|------|
| 型 / client | `LearningItemCandidate` / `extractCandidates` / `fetchCandidates` / `acceptCandidate` / `rejectCandidate` |
| 状態 | `useTutorSourceCandidates`。accept/reject は API 成功後にだけ status を更新する |
| 表示 | `TutorCandidateList` + `TutorCandidateCard`。item type / status / evidence を表示 |
| 再抽出 | 既存の accepted / rejected は一覧に残る。Backend が skipped として返す |
| エラー | 503 API key、503 一時障害、502 不正応答をユーザー向け文言へ変換 |

| 観点 | 自動テスト |
|------|------------|
| 抽出ボタン / loading / 多重実行防止 | `TutorSourceDetail.test.tsx` |
| 4 種 item type と evidence | 同上 |
| accept / reject 成功と API 失敗 | 同上 |
| empty / 既存 status / 再抽出 | 同上 |
| client 契約 | `tutorApi.test.ts` |
| Phase 1 回帰 | `TutorPhase1Flow.test.tsx` / `TutorFlow.test.tsx` / `App.test.tsx` |

## Phase 2 抽出品質ハーネス（Issue #136）

LLM抽出の品質を目視だけに依存させない。固定 Source fixture と
deterministic なチェックを主、実 LLM 実行を補助とする。
LLM-as-judge は品質ゲートにしない。詳細は `docs/tutor_extraction_quality.md`。

```text
固定 fixture A/B/C/D
  -> ExtractionService（fake または実 LLM）
  -> evidence / 契約 / duplicate / hallucination / must-have recall
  -> provider / model / extraction_version をレポートに残す
```

通常の pytest は API key なしで通る。実 LLM は
`scripts/evaluate_tutor_extraction.py` または `RUN_LIVE_LLM=1 pytest -m live_llm`。

| 観点 | 自動テスト |
|------|------------|
| fixture A〜D と期待値が定義されている | `test_fixed_source_fixtures_cover_required_patterns` |
| must-have / must-not が文書化されている | `test_must_have_and_unacceptable_expectations_are_documented` |
| evidence / 必須フィールド / 件数上限 | `test_evidence_*` / `test_candidate_count_limit_is_checked` |
| hallucination / 過剰抽出 / duplicate | `test_obvious_hallucination_*` / `test_fixture_b_detects_over_extraction` / `test_duplicate_keys_*` |
| provider / model / prompt version | `test_report_keeps_provider_model_and_prompt_version` |
| API key なしの CI | `test_valid_fixture_a_extraction_passes_contract_and_must_haves` |
| OpenAI 非依存 | `test_quality_modules_do_not_import_openai` |

## Phase 2 vertical slice（Issue #137）

Phase 2 で追加した Candidate extraction を個別部品ではなく、
ユーザー操作として一本につながった vertical slice として検証する。

```text
保存済み SourceDocument
  -> Source 詳細
  -> 学習候補抽出（fake LearningItemExtractor）
  -> LLM structured response
  -> evidence validation / normalization / dedup
  -> LearningItemCandidate 保存
  -> Candidate 一覧と evidence 表示
  -> 1件 accept / 1件 reject
  -> accepted だけ LearningItem になる
  -> rejected は履歴として残る
  -> SourceRef / evidence provenance
  -> 再抽出しても重複爆発しない
  -> DB 再 open 後も status / LearningItem が残る
```

推奨 fixture:

```text
Je me suis rendu compte qu'il fallait changer de stratégie.
```

vertical slice の fake extractor は次を返す。

- `se rendre compte de` / expression
- `il fallait` / grammar
- `stratégie` / vocabulary
- `changer` / conjugation

加えて、同一 expression の表記ゆれと本文範囲外 span を混ぜ、
deterministic layer が重複統合・除外することを確認する。
実 LLM の品質確認は #136 の評価経路で行い、この統合テスト自体は
fake provider で deterministic にする。

| 観点 | 自動テスト |
|------|------------|
| Source → 抽出 → 採否 → LearningItem → 再抽出 → DB 再 open | `test_phase2_source_to_candidate_to_learning_item_vertical_slice` |
| 4種 item type と evidence | 同上 / `TutorPhase2Flow.test.tsx` |
| 既存 LearningItem への統合 | `test_phase2_accept_merges_existing_learning_item` |
| provider 障害で既存を壊さない | `test_phase2_provider_failure_leaves_existing_candidates` |
| Exercise 生成 API をまだ持たない | `test_phase2_does_not_expose_exercise_generation_endpoints` |
| 既存 quiz / TTS / Source ingestion の回帰 | `test_phase2_existing_quiz_and_tts_contracts_are_unchanged` |
| Frontend 抽出・採否・再表示 | `TutorPhase2Flow.test.tsx` |
| Frontend loading / error / empty | 同上 |
| スマホ相当幅の抽出・採否ボタン | 同上 |

## Phase 2 の品質境界

Phase 2 完了時点で、次の境界が明確である。

### LLM が決めること

- 学習候補の提案
- 日本語の意味 / 説明案
- CEFR 推定
- evidence span 案
- confidence 案

### deterministic layer が保証すること

- schema validity（未知 enum・必須欠落・confidence 範囲・件数上限）
- evidence が Source 本文の範囲内で、空白のみではないこと
- canonical_form / meaning_ja の正規化
- 同一 Source 内の duplicate 抑止
- Candidate の状態遷移（`candidate` からのみ終端へ）
- accept したものだけ LearningItem 化
- 既存 LearningItem との normalization key 一致時は source_ref 追加で統合
- persistence 整合性（同一 TX、再 open、provider 障害時に既存を壊さない）

### 人間が決めること

- Candidate を学習対象として採用するか

LLM 出力をそのまま LearningItem にしない。Frontend は provider 生応答や
Candidate.metadata を通常 UI に出さない。

## Phase 2 Exit Criteria（Issue #107）との対応

Issue #107 の Phase 2 は、保存済み Source から LLM が学習候補を提案し、
ユーザーが根拠を確認して採用したものだけが LearningItem になること。

| Exit Criteria | 満たした実装 | 自動テスト |
|---------------|--------------|------------|
| 保存済み Source から学習候補を抽出できる | `POST /api/tutor/sources/{id}/candidates/extract` | `test_phase2_source_to_candidate_to_learning_item_vertical_slice` |
| 抽出結果は structured `LearningItemCandidate` として保持される | `CandidateService` + SQLite | 同上 / `test_extract_saves_candidates` |
| vocabulary / expression / grammar / conjugation を扱える | domain `LearningItemType` + 抽出 schema | 同上 / `test_extract_maps_four_item_types_to_candidates` / `TutorPhase2Flow.test.tsx` |
| 各 Candidate に原文 evidence を保持・表示できる | `evidence_span` + 再構成 `evidence_text` | 同上 / `TutorCandidateCard` |
| malformed / hallucinated span 等を deterministic に排除できる | `candidate_normalization` | 同上（範囲外 span） / `test_span_outside_source_is_excluded` |
| 同一 Source の重複 Candidate が抑止される | `item_normalization_key` | 同上（表記ゆれ） / `test_duplicate_candidates_are_merged_to_one` |
| ユーザーが Candidate を accept / reject できる | 採否 API + Source 詳細 UI | 同上 / `TutorPhase2Flow.test.tsx` |
| accept した Candidate だけ LearningItem になる | `CandidateService.accept` | 同上 |
| rejected Candidate は履歴として残り LearningItem にならない | status=`rejected`、Item 非作成 | 同上 / `test_reject_does_not_create_learning_item` |
| 既存 LearningItem と一致する場合に重複作成を抑止できる | normalization key で merge | `test_phase2_accept_merges_existing_learning_item` |
| LearningItem に SourceRef / evidence provenance が残る | `source_refs` | `test_phase2_source_to_candidate_to_learning_item_vertical_slice` |
| 再抽出で Candidate / LearningItem が無制限増殖しない | skipped + 状態維持 | 同上 / `test_reextract_does_not_duplicate_pending_candidates` |
| DB 再 open 後も状態が保持される | file SQLite | `test_phase2_source_to_candidate_to_learning_item_vertical_slice` |
| 通常 CI は LLM API key なしで通る | fake extractor / mocked OpenAI | 同上（`OPENAI_API_KEY` 削除） / `test_domain_and_service_work_without_openai_api_key` |
| 実 LLM 抽出品質を任意評価できる fixture / 評価経路がある | `evaluation/` + `evaluate_tutor_extraction.py` | `tests/test_extraction_quality.py` / `docs/tutor_extraction_quality.md` |
| 既存 Source ingestion / quiz / TTS に回帰がない | 既存 API は Tutor 抽出と独立 | `test_phase2_existing_quiz_and_tts_contracts_are_unchanged` / `App.test.tsx` |
| スマホ相当幅で Candidate review が実用的である | 全幅抽出ボタン、採否 `minHeight: 44`、折り返し | `TutorPhase2Flow.test.tsx` |
| `bash scripts/quality-check.sh` が通る | ruff / pytest / lint / frontend test / build | 作業完了時に実行 |
| Phase 2 境界と Phase 3 への引継ぎを記載する | 本セクション | 本ドキュメント |

## Phase 3 への引き継ぎ

Phase 3 では accepted `LearningItem` を実際の Exercise へ接続する。
Issue #145 で契約・適用条件・skill direction を定義した。
Issue #146 で vocabulary / expression の deterministic な基本 Exercise
生成を追加した。Issue #147 で Source evidence からの cloze 生成を追加した。
Issue #148 で conjugation を既存動詞活用へ安全に接続する adapter を追加した。
Issue #149 で Exercise の server-side 採点と LearningEvent 記録 API を追加した。
Issue #150 で accepted LearningItem から手動開始できる Practice Session を
組み立てる API を追加した。Issue #151 で Frontend から解ける Practice
Session UI を追加した。Issue #152 でこれらを一本の vertical slice として
閉じ、Phase 3 Exit Criteria を固定した。
Phase 2 では LearningItem を作れるところまでで止め、
以下はまだ行わない。

- 自動学習開始
- long-term review UI
- Tutor recommendation
- URL / PDF / YouTube ingestion
- by_direction の長期 SRS 最適化
- LLM semantic grading

Phase 3 へ進む前提は、Phase 0〜2 が `bash scripts/quality-check.sh` で
継続して通ることである。

## Phase 3 — LearningItem → Exercise 契約（Issue #145）

Phase 2 で確定した `LearningItem` を、実際の学習問題へ変換するための
共通 Exercise 契約。既存クイズを全面的に作り直すのではなく、Tutor layer
から「この LearningItem にはどの Exercise を出せるか」を判断し、
既存 / 新規の出題実装へ委譲できる薄い境界にする。

```text
LearningItem
  -> Exercise eligibility / policy
  -> ExerciseSpec
  -> evaluator（Issue #149）
  -> LearningEvent（exercise_version / skill_direction を metadata で追跡）
```

実装は `backend/app/domain/exercise.py`。DB / FastAPI / OpenAI に依存しない。
Exercise 自体は永続化しない。同じ `(learning_item_id, exercise_type, exercise_version)`
から同じ Exercise を再構成できることを優先する。

### 共通契約

| 型 | 責務 |
|----|------|
| `ExerciseSpec` | 出題の内部契約。prompt / options / source_context を持つ。正解は持たない |
| `PublicExercise` | Frontend 向け DTO。`metadata` と正解・判定内部情報を持たない |
| `ExerciseAnswerKey` | evaluator 内部用。`to_public_exercise` に混ぜない |
| `ExerciseEligibility` | item × ExerciseType の適用可否と skip 理由 |

`ExerciseSpec.metadata` に `expected` / `answer` / `correct_index` 等を載せると
ValidationError。Frontend へ返すときは必ず `to_public_exercise` を通す。

`response_kind`:

| 値 | 用途 |
|----|------|
| `choice` | 選択肢（meaning_recognition / noun_gender / noun_article） |
| `text` | 文字列入力（ja_to_fr / cloze / verb_conjugation / fr_to_ja） |
| `reconstruction` | 表現の再構成（`expression_reconstruction`） |

### ExerciseType と既存型の対応

| ExerciseType | 由来 | Phase 3 での扱い |
|--------------|------|------------------|
| `meaning_recognition` | Tutor | 意味の選択。日本語自由記述ではない |
| `fr_to_ja` | Tutor（LearningEvent 記録用） | 日本語自由記述の意味判定が必要なため生成しない |
| `ja_to_fr` | Tutor | canonical_form との照合が可能な production |
| `cloze` | Tutor | source cloze。evidence があるときだけ |
| `expression_reconstruction` | Roadmap の expression 再構成。cloze とは別型 | 複数トークンの expression のみ |
| `verb_conjugation` | 既存動詞クイズ | lemma が `CONJUGATIONS` にあり、`metadata.tense` が既存時制と一致する conjugation のみ委譲 |
| `noun_gender` | 既存名詞クイズ | LearningItem から新規生成しない |
| `noun_article` | 既存冠詞クイズ | LearningItem から新規生成しない |

文法選択問題（もっともらしい誤答選択肢の LLM 生成）は型を増やさない。
grammar は `meaning_recognition` と source cloze に限定する。

### ExerciseType → SkillDirection

曖昧な形式は暗黙に決めず、`skill_direction_for` が一元管理する。
1つの ExerciseType は常に 1つの SkillDirection。

| ExerciseType | SkillDirection | 理由 |
|--------------|----------------|------|
| `meaning_recognition` | recognition | 仏語を見て意味が分かるか |
| `fr_to_ja` | recognition | 仏語の理解（生成はしない） |
| `ja_to_fr` | production | 仏語を自力で書く |
| `cloze` | production | 空所に仏語を入れる |
| `expression_reconstruction` | production | 表現を組み直す |
| `verb_conjugation` | production | 活用形を書く |
| `noun_gender` | recognition | 性を識別する |
| `noun_article` | production | 冠詞付き形を選ぶ |

Phase 0 と同様、Issue #145 時点では `LearnerState.by_direction` は更新しない。
集計は Issue #161。mapping 自体は `SKILL_DIRECTION_BY_EXERCISE_TYPE` が
source of truth。

### LearningItemType ごとの eligibility

`eligible_exercise_types(item)` は metadata を満たすものだけを返す。
満たさない組合せは `list_exercise_eligibility` で skip 理由付きにする。
`make_exercise_spec` は unsupported を `UnsupportedExerciseError` で拒否する。

| item_type | Phase 3 で安全に生成可能な Exercise | 追加条件 |
|-----------|-------------------------------------|----------|
| vocabulary | meaning_recognition / ja_to_fr / source cloze | cloze は evidence_span 付き source_ref |
| expression | meaning_recognition / ja_to_fr / reconstruction / source cloze | reconstruction は複数トークン。cloze は evidence |
| grammar | meaning_recognition / source cloze | cloze は evidence。文法選択問題は作らない |
| conjugation | source cloze / 条件付き verb_conjugation | cloze は evidence。verb_conjugation は lemma が `CONJUGATIONS` にあり、tense が既存実装と一致すること。tense 欠落は présent 扱いしない |

skip 理由:

| skip_reason | 意味 |
|------------|------|
| `unsupported_combination` | その item_type に出さない形式 |
| `missing_source_evidence` | source cloze なのに evidence がない |
| `source_not_found` | evidence の SourceDocument が渡されていない / 存在しない |
| `evidence_span_out_of_range` | evidence_span が Source 本文の範囲外 |
| `evidence_span_empty` | 再構成結果が空または whitespace のみ |
| `context_unavailable` | blank 前後の context を十分な長さで切り出せない |
| `unknown_conjugation_lemma` | 既存動詞データに接続できない |
| `missing_conjugation_tense` | conjugation adapter に必要な tense metadata が無い |
| `unsupported_conjugation_tense` | tense はあるが既存 CONJUGATIONS の対応範囲外 |
| `unsupported_conjugation_mood` | mood があるが既存実装（indicatif）と一致しない |
| `requires_semantic_grading` | 日本語自由記述の意味判定が必要（fr_to_ja） |
| `existing_quiz_only` | 既存クイズ専用（noun_gender / noun_article） |
| `insufficient_expression_tokens` | 再構成できない短い expression |
| `inactive_item` | suspended / mastered。新規学習 Session の対象外 |
| `insufficient_distractors` | meaning_recognition のユニークな誤答選択肢が足りない |
| `generation_not_implemented` | 契約上は出せるが、この生成器の初期対象外 |

metadata 不足の Exercise を無理に生成しない。
文法選択の誤答選択肢や日本語自由記述の意味判定を、Phase 3 で LLM に
丸投げして正解判定しない。

### versioning

`EXERCISE_VERSION`（現行 `exercise-v1`）を `ExerciseSpec.exercise_version` に載せる。
`exercise_event_metadata(spec)` が LearningEvent.metadata へ
`exercise_version` / `skill_direction` / `response_kind` /
`generation_method` / `reconstruction_key` を載せる。正解は含めない。

生成ロジックを後から変えるときは version を bump する。
過去の LearningEvent から「どの版で回答したか」を追跡できる。

### 既存クイズとの関係

既存の動詞・名詞・冠詞クイズ実装（`conjugation.py` / `noun.py` と quiz API）は
変更しない。Tutor は eligibility を見て、lemma と tense が既存 domain と
一致する conjugation だけ既存 `verb_conjugation` へ委譲する。
LLM が「現在形だから既存 quiz へ流してよい」と最終判断しない。

item 単位の Exercise 取得・回答 API は Issue #149。
Phase 2 の `test_phase2_does_not_expose_exercise_generation_endpoints` は
generic な `/api/tutor/exercises` 等を禁止したまま維持する。

| 観点 | 自動テスト |
|------|------------|
| item type ごとの eligible 一覧が deterministic | `test_eligible_exercises_by_item_type_are_deterministic` |
| unsupported を拒否 / skip できる | `test_unsupported_combinations_are_explicitly_skipped` / `test_make_exercise_spec_rejects_unsupported_combination` |
| ExerciseType → SkillDirection が一意 | `test_exercise_type_to_skill_direction_is_unique_and_total` |
| 正解情報が public DTO へ混入しない | `test_public_dto_does_not_include_internal_answer_fields` |
| domain が FastAPI / SQLAlchemy / OpenAI 非依存 | `test_domain_module_does_not_depend_on_fastapi_sqlalchemy_or_openai` |
| exercise_version を LearningEvent で追跡できる | `test_learning_event_can_track_exercise_version` |

### Phase 3 の残り（#145〜#151 時点のスコープ外。#152 で vertical slice として閉じる）

- due review session（Phase 4）
- ReviewSchedule の direction 分離は Issue #162 で実装した

## Phase 3 — vocabulary / expression の deterministic 生成（Issue #146）

Issue #145 の契約の上に、accepted かつ active な `vocabulary` /
`expression` LearningItem から基本 Exercise を組み立てる。
出題のたびに LLM が問題と正解を作る構成にはしない。
LearningItem に確定済みの情報だけを使い、OpenAI API を要求しない。

```text
LearningItem (+ active pool, seed)
  -> eligibility / skip reason
  -> ExerciseSpec + ExerciseAnswerKey
  -> PublicExercise（正解を含めない）
```

実装は `backend/app/domain/exercise_generation.py`。
DB / FastAPI / OpenAI に依存しない。HTTP 変換はこのモジュールの責務ではない
（取得・回答 API は Issue #149）。

### 初期対象

| ExerciseType | 形式 | 内容 |
|--------------|------|------|
| `meaning_recognition` | recognition / choice | `canonical_form` を提示し、`meaning_ja` を選ぶ |
| `ja_to_fr` | production / text | 日本語意味を提示し、`canonical_form` を入力する |
| `expression_reconstruction` | production / reconstruction | expression を語/まとまりに分けて再構成する |

`fr_to_ja` の日本語自由記述は `meaning_ja` との単純文字列一致で判定しない。
FR→JA 方向は `meaning_recognition` が担う。

### meaning recognition

- 正解: 対象 Item の `meaning_ja`
- distractor: 他の **active** LearningItem の `meaning_ja`
- 同じ意味（NFC + 空白正規化）の重複 option は出さない
- 目標 4 択。ユニークな distractor が 1 件もなければ生成せず
  `insufficient_distractors`
- distractor 選択と option 順は injectable な `seed` と
  `(item.id, exercise_type, exercise_version)` から deterministic

### ja_to_fr

- prompt には日本語意味だけを載せ、canonical_form は載せない
- 正解根拠は `ExerciseAnswerKey.expected_answers` に `canonical_form` を保持する
- 正解判定そのもの（evaluator）は後続 Issue

### expression reconstruction

- whitespace で分割し、apostrophe / elision（`l'heure`, `s'en aller`）と
  hyphen は切らない（`tokenize_canonical_form`）
- 語順の正解は canonical form から導出する
- 提示順は seed 付きで shuffle し、`options` に載せる
- 1 token しかない item には出さない（既存の eligibility）

### 共通方針

- suspended / mastered Item は新規学習 Session 対象外（`inactive_item`）
- unsupported / 材料不足は例外で全体停止せず、skip reason を返す
- 同じ Item + seed / version から同じ Exercise を生成できる
- 正解は public DTO に含めない
- grammar の meaning_recognition は対象外（この Issue）
- source cloze は Issue #147
- conjugation の既存動詞 adapter は Issue #148

| 観点 | 自動テスト |
|------|------------|
| vocabulary meaning recognition | `test_vocabulary_meaning_recognition_uses_pool_meanings` |
| expression meaning recognition | `test_expression_meaning_recognition_uses_japanese_options` |
| ja_to_fr prompt / 内部正解の分離 | `test_ja_to_fr_keeps_canonical_form_as_internal_answer` |
| expression reconstruction | `test_expression_reconstruction_shuffles_tokens_without_breaking_elision` |
| distractor 不足時の skip | `test_meaning_recognition_skips_when_distractors_are_insufficient` |
| duplicate meaning を option に入れない | `test_duplicate_meanings_are_not_used_as_options` |
| suspended / mastered 除外 | `test_suspended_and_mastered_items_are_skipped` / `test_inactive_items_are_not_eligible_for_new_session` |
| deterministic generation | `test_generation_is_deterministic_for_same_item_and_seed` |
| 日本語自由記述を完全一致で採点しない | `test_fr_to_ja_is_not_graded_by_meaning_string_match` |
| API key なしで動く | `test_generation_works_without_openai_api_key` |

## Phase 3 — Source evidence からの cloze 生成（Issue #147）

Phase 3 の差別化は、一般的な単語帳ではなく「自分が読んだ文脈から学ぶ」
ことにある。accepted `LearningItem` の `SourceRef.evidence_span` と
元 Source 本文から、deterministic に cloze Exercise を組み立てる。

```text
LearningItem
  -> SourceRef選択（oldest-source）
  -> SourceDocument取得
  -> evidence_span検証
  -> 前後context切り出し
  -> evidence部分をblank化
  -> cloze ExerciseSpec + ExerciseAnswerKey
```

実装は `backend/app/domain/exercise_generation.py` の cloze 経路。
DB / FastAPI / OpenAI に依存しない。HTTP 変換はこのモジュールの責務ではない。

### 対象 item type

`vocabulary` / `expression` / `grammar` / `conjugation`。
有効な SourceRef / evidence がなければ cloze を生成しない。
grammar の初期 Exercise として source cloze を採用する。
もっともらしい誤答文法選択肢を LLM で都度生成しない。

### cloze 仕様

- 正解は `SourceDocument.content[start:end]` から再構成する
- LLM が返した raw evidence text（`EvidenceSpan.text`）や
  `canonical_form` を正解にしない
- prompt / `source_context` には blank 済みの前後文脈を載せる
- context 長は `CLOZE_CONTEXT_MAX_CHARS`（160）を上限とし、
  長文 Source 全文を返さない。収まるなら evidence を含む文を優先する
- 改行 / Unicode / apostrophe は Source slice のまま残す
- 空欄は `____`。文字列 replace ではなく span 位置で置き換える

例:

```text
Je me suis rendu compte qu'il fallait changer de stratégie.
```

evidence が `rendu compte` 相当を指す場合:

```text
Je me suis ____ qu'il fallait changer de stratégie.
```

### SourceRef が複数ある場合

有効な evidence（Source が存在し、span が本文内で空でなく、
context を切れる）だけを候補にし、**oldest-source** で1件選ぶ。

- `SourceDocument.created_at` 昇順
- 同刻なら `source_document_id` 昇順
- さらに同順位なら `evidence_span.start` / `end` 昇順

暗黙の random は使わない。invalid な ref は出題に使わず、
valid な別 ref があればそちらを使う。

### invalid / unavailable

既存データ不整合を無言で誤問題へ変換しない。skip reason:

| skip_reason | 条件 |
|------------|------|
| `missing_source_evidence` | SourceRef なし、または evidence_span なし |
| `source_not_found` | 参照先 SourceDocument が渡されていない |
| `evidence_span_out_of_range` | span が本文範囲外 |
| `evidence_span_empty` | 再構成結果が空 / whitespace のみ |
| `context_unavailable` | evidence が本文全体、または上限内に前後 context を切れない |

| 観点 | 自動テスト |
|------|------------|
| 4 item type の cloze | `test_cloze_is_generated_for_four_item_types` |
| 正解は Source slice | `test_cloze_answer_is_reconstructed_from_source_slice_not_llm_text` |
| source 外 span の拒否 | `test_cloze_rejects_span_outside_source` |
| context 長上限 | `test_cloze_caps_context_length` / `test_cloze_uses_containing_sentence_instead_of_full_long_source` |
| 複数 SourceRef の選択 | `test_multiple_source_refs_choose_oldest_deterministically` |
| apostrophe / Unicode / 改行 | `test_cloze_preserves_apostrophe_unicode_and_newlines` |
| SourceRef なしの skip | `test_cloze_skips_item_without_source_ref` |
| Source 不存在 / 空 evidence / context 不能 | `test_cloze_skips_missing_source_document` / `test_cloze_skips_whitespace_only_evidence` / `test_cloze_skips_when_context_cannot_be_built` |

## Phase 3 — conjugation の既存動詞活用 adapter（Issue #148）

`conjugation` LearningItem を、既存の動詞活用データ・問題生成・正解判定へ
安全に接続する。既存クイズをコピーして別実装を作らず、adapter として再利用する。
metadata 不足や時制不一致のときに誤った問題を生成しない。

```text
conjugation item
  -> lemma 特定 + CONJUGATIONS に動詞がある
  -> metadata.tense が明示され、既存実装の時制と一致する
  -> 既存 pronoun 集合から seed 付きで1つ選ぶ
  -> get_correct_answer で正解を取る
  -> 条件を満たさなければ verb_conjugation を出さず、source cloze へ fallback
```

実装は `backend/app/domain/conjugation_adapter.py`。生成は
`exercise_generation.py` の verb_conjugation 経路。既存 `conjugation.py` の
活用データは複製しない。HTTP 変換はこのモジュールの責務ではない
（取得・回答 API は Issue #149）。Frontend は対象外。

### adapter eligibility

次をすべて満たすときだけ `verb_conjugation` を生成する。

- lemma が特定できる（`metadata.lemma` 優先、なければ `canonical_form`）
- 既存 `CONJUGATIONS` にその動詞がある
- `metadata.tense` が明示されている
- その tense が `CONJUGATIONS[lemma]` のキーと一致する
- `metadata.mood` がある場合は `indicatif` のみ許可

満たさない場合の skip reason:

| skip_reason | 条件 |
|------------|------|
| `unknown_conjugation_lemma` | lemma が既存動詞データにない |
| `missing_conjugation_tense` | tense metadata が無い。présent を補完しない |
| `unsupported_conjugation_tense` | tense はあるが既存実装の対応範囲外（例: imparfait） |
| `unsupported_conjugation_mood` | mood が indicatif 以外 |

adapter 対象外でも LearningItem 自体は無効にしない。source cloze が
出せるならそちらへ fallback する。

### metadata

安全な判定のため、extraction / normalization / accept で最小限の
grammar metadata を載せる。

| フィールド | 永続化する値 | 備考 |
|------------|--------------|------|
| `lemma` | 正規化後の canonical_form | conjugation では必須相当 |
| `tense` | `présent` / `imparfait` / `futur` / `passé composé` | 許可リスト外は捨てる |
| `mood` | `indicatif` / `subjonctif` / `conditionnel` / `impératif` | 任意。許可リスト外は捨てる |

LLM が tense を返しても、adapter 可否の最終判断は metadata +
`CONJUGATIONS` lookup だけが行う。既存 Candidate / LearningItem との
後方互換を保つ（tense 欠落の Item は cloze のみ）。

### 既存 domain の再利用

- 正解は `get_correct_answer(verb, tense, pronoun)` から取る
- pronoun は `CONJUGATIONS[lemma][tense]` のキー順を再利用する
- 既存 quiz API / `conjugation.py` のデータ辞書は変更しない

| 観点 | 自動テスト |
|------|------------|
| 既存対応動詞 + present | `test_adapter_is_eligible_for_known_verb_and_present` |
| 未対応 lemma | `test_adapter_skips_unknown_lemma` |
| tense 不一致 | `test_adapter_skips_tense_mismatch` |
| metadata 欠落を present 扱いしない | `test_adapter_does_not_default_missing_tense_to_present` |
| adapter 正解が既存 domain と一致 | `test_adapter_answer_matches_existing_domain` |
| source cloze fallback | `test_source_cloze_fallback_when_adapter_is_ineligible` |
| 活用データを複製しない | `test_adapter_does_not_copy_conjugation_tables` |

## Phase 3 — Exercise 回答判定と LearningEvent 記録（Issue #149）

生成した Tutor Exercise への回答を Backend で判定し、既存の
`LearningEvent -> LearnerState -> ReviewSchedule` パイプラインへ接続する。
Frontend から `expected_answer` を送り返して採点しない。
Backend は LearningItem / Source / 既存動詞 domain から同じ Exercise を
再構成し、正解根拠を server-side で取得する。

```text
GET Exercise（PublicExercise。正解なし）
  -> user response
  -> server-side evaluator
  -> correct / incorrect
  -> LearningEvent append
  -> LearnerState update
  -> ReviewSchedule update
  -> feedback（correct_answer は回答後のみ）
```

実装:

- 採点・正規化: `backend/app/domain/exercise_evaluation.py`
- ユースケース: `backend/app/services/exercise_service.py`
- HTTP: `GET/POST /api/tutor/items/{item_id}/exercises/{exercise_type}`
- 記録は既存 `TutorService.record_review` を再利用する

Frontend session UI は Issue #151。LLM semantic grading は行わない。

### エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| GET | `/api/tutor/items/{item_id}/exercises/{exercise_type}` | PublicExercise。正解・metadata は返さない |
| POST | `/api/tutor/items/{item_id}/exercises/{exercise_type}/answer` | 採点し LearningEvent を記録（201） |

GET と POST は同じ `DEFAULT_GENERATION_SEED` で Exercise を再構成する。
Exercise 自体は永続化しない。

### 回答形式別 evaluation

| response_kind | 判定 |
|---------------|------|
| choice | option 文字列（meaning_ja）を安定識別子として比較。index / 表示順には依存しない |
| text | `normalize_french_production` で揃えてから `expected_answers` と比較 |
| reconstruction | 表示 token の順序を、同じ正規化をかけた正解順と比較 |

フランス語 production の正規化（順序固定）:

1. Unicode NFC
2. typographic apostrophe（U+2019 等）を ASCII `'` へ置換
3. 前後空白除去と連続 Unicode 空白の圧縮
4. casefold（大文字小文字を無視）

**accent は除去しない。** `été` と `ete` は不一致。
日本語自由記述（fr_to_ja）は Phase 3 でも生成・採点しない。

### LearningEvent metadata

`exercise_event_metadata` が載せる追跡情報:

- `exercise_version`
- `skill_direction`
- `response_kind`
- `generation_method`（`deterministic` / `source_cloze` / `conjugation_adapter`）
- `reconstruction_key`
- cloze のとき `source_document_id`

正解は含めない。`exercise_type` は LearningEvent の既存フィールド。
`LearnerState.by_direction` の更新は Issue #161。source of truth は
`exercise_type` の mapping であり、この metadata ではない。

### idempotency

client は回答 POST に `id`（LearningEvent.id）を付けられる。
重複は既存方針どおり 409。LearnerState は二重加算しない。

### feedback

回答後のみ:

- `correct` / `correct_answer` / `given`
- `explanation_ja` optional（LearningItem 由来）
- `source_context` optional（cloze の blank 済み文脈）
- `event` / `learner_state` / `review_schedule`

### HTTP status

| 状況 | status |
|------|--------|
| 問題取得成功 | 200 |
| 回答記録成功 | 201 |
| item 不存在 | 404 |
| unsupported / inactive（suspended, mastered）/ 材料不足 | 422（`skip_reason` 付き） |
| malformed な回答（空、response_kind と型不一致） | 422 |
| duplicate event id | 409 |

inactive item は出題不可として 422 に固定する。409 は重複 ID 専用。

| 観点 | 自動テスト |
|------|------------|
| meaning recognition 正誤 | `test_meaning_recognition_correct_and_incorrect` |
| ja_to_fr 正規化 | `test_ja_to_fr_normalizes_and_rejects_missing_accent` |
| accent 誤りを正解にしない | `test_accent_error_is_not_accepted_as_correct` |
| apostrophe 差 | `test_apostrophe_variants_are_accepted` |
| cloze / reconstruction | `test_cloze_and_reconstruction` / `test_cloze_grades_source_slice` |
| verb adapter | `test_verb_conjugation_adapter_answer` |
| LearningEvent 1件追加と state/schedule | `test_correct_and_incorrect_each_append_one_event_and_update_state` |
| duplicate で二重適用しない | `test_duplicate_answer_returns_409_without_double_apply` |
| GET に正解が漏れない | `test_get_exercise_omits_correct_answer` |

## Phase 3 — Practice Session 組み立て（Issue #150）

accepted かつ active な LearningItem を複数まとめ、ユーザーが手動で
開始できる最小の Tutor Practice Session を組み立てる。
Phase 4 の「今日の復習」や due 優先度は導入しない。

```text
active LearningItems
  -> eligible Exercise 列挙
  -> session policy
  -> PracticeSession
  -> Exercise 回答（#149）
  -> 次の Exercise
```

実装:

- 選択 policy: `backend/app/domain/practice_session.py`
- ユースケース: `backend/app/services/practice_session_service.py`
- HTTP: `POST /api/tutor/practice/sessions`
- 補助: `GET /api/tutor/items`（active Item の最小一覧。管理検索はしない）

Session 自体は DB に保存しない。学習履歴の source of truth は
回答ごとの LearningEvent。`session_id` はエフェメラルで、再取得 API は持たない。

### 入力

`source_id` と `item_ids` は同時指定できない。どちらも無ければ
active LearningItem 全体から選ぶ。Candidate は直接入れない。

| フィールド | 意味 |
|------------|------|
| `source_id` | その Source を `source_refs` に持つ Item だけ |
| `item_ids` | 明示した Item。重複 ID は 1 回にまとめる |
| `question_count` | 上限（default 5 / max 20）。候補が少なければ水増ししない |
| `seed` | 選択順の再現用。省略時は `tutor-practice` |

Exercise の prompt / options は既存 GET/answer と同じ
`DEFAULT_GENERATION_SEED` で再構成する。session seed は並び順だけに使う。

### Selection policy

1. **active のみ** — suspended / mastered は通常の新規 practice 対象外。
   `item_ids` や `source_id` で明示された inactive は `inactive_item` で skip
2. **重複抑止** — 1 Session 内で同じ `(learning_item_id, exercise_type)` を入れない
3. **recognition / production** — 可能な範囲で交互に含める。高度な個人最適化はしない
4. **unsupported は skip** — 生成できない Item で Session 全体を失敗させない
5. **deterministic** — 同一入力 + 同一 seed なら同一の出題列

due_at / overdue / lapse / mastery / recognition-production imbalance では
並べ替えない。

### HTTP status

| 状況 | status |
|------|--------|
| 組み立て成功（0件を含む） | 200 |
| Source / Item 不存在 | 404 |
| `source_id` と `item_ids` の同時指定、`question_count` 範囲外 | 422 |

| 観点 | 自動テスト |
|------|------------|
| source_id で該当 Item のみ | `test_source_id_selects_only_items_from_that_source` / `test_practice_session_source_id_filter` |
| item_ids 指定 | `test_item_ids_select_only_requested_items` / `test_practice_session_item_ids_filter` |
| active のみ | `test_unfiltered_session_uses_active_items_only` / `test_explicit_inactive_item_is_skipped_with_reason` |
| question_count 上限と非重複 | `test_question_count_caps_session_without_padding_duplicates` |
| recognition / production 混在 | `test_mixes_recognition_and_production_when_both_exist` |
| unsupported skip | `test_unsupported_item_is_skipped_without_failing_session` |
| seed 固定 | `test_same_seed_is_deterministic` / `test_practice_session_seed_is_deterministic` |
| 0件 | `test_empty_items_returns_empty_session` / `test_practice_session_zero_items` |
| due を先取りしない | `test_selection_policy_does_not_use_due_or_review_schedule` |

## Phase 3 — Practice Session Frontend UI（Issue #151）

Issue #150 の Session を Frontend から解けるようにする。
Candidate 未採用のまま Exercise には進まない。Session 自体は
永続化せず、回答は既存の Exercise 採点 API（Issue #149）へ送る。

```text
Tutor / Source詳細
  -> 「学習する」
  -> 出題数選択
  -> Practice Session 開始
  -> 問題表示
  -> 回答
  -> 判定
  -> 正解 / 意味 / 解説 / 出典
  -> 次へ
  -> Session 結果
```

実装:

- API client: `createPracticeSession` / `submitExerciseAnswer`
- hook: `frontend/src/hooks/usePracticeSession.ts`
- renderer: `PracticeExerciseCard`（choice / text / reconstruction）
- reconstruction: タップ中心。drag は必須にしない
- TTS: 既存 `useTTS`。失敗しても Session は止めない

| 観点 | 自動テスト |
|------|------------|
| Source / Tutor 一覧から開始 | `TutorFlow.test.tsx` / `TutorSourceList.test.tsx` / `TutorSourceDetail.test.tsx` |
| choice / text / cloze / reconstruction / verb | `PracticeSessionFlow.test.tsx` / `PracticeExerciseCard.test.tsx` |
| 正誤 feedback と explanation / evidence | 同上 |
| 送信失敗時に現在問題を保持 | `PracticeSessionFlow.test.tsx` |
| TTS 失敗で学習フローが止まらない | `PracticeExerciseCard.test.tsx` |
| Session 完了結果 | `PracticeSessionFlow.test.tsx` |

## Phase 3 vertical slice（Issue #152）

Issue #145〜#151 で追加した Exercise 生成・回答判定・Practice Session・
Frontend を、ユーザー操作として一本につながった vertical slice として検証する。

Phase 3 のゴールは、Phase 2 で accepted になった LearningItem を
**実際に解き、その結果が LearningEvent / LearnerState / ReviewSchedule へ残ること**。

必須フロー:

```text
1. SourceDocumentを保存
2. CandidateをacceptedにしてLearningItemを作成
3. LearningItemからeligible Exerciseを生成
4. Practice Sessionを開始
5. recognition問題へ回答
6. production問題へ回答
7. correct / incorrect feedbackを受ける
8. LearningEventがappendされる
9. LearnerStateが更新される
10. ReviewScheduleが更新される
11. Session結果を表示
12. DB再open後もEvent / State / Scheduleが残る
```

推奨 fixture は Phase 2 と同じ原文:

```text
Je me suis rendu compte qu'il fallait changer de stratégie.
```

LearningItem 例: `se rendre compte de` / expression / 〜に気づく。
ここから meaning recognition / ja_to_fr または reconstruction / source cloze
を安全に生成できる。

conjugation adapter fixture は既存 domain の現在形動詞（`parler` + `présent`）を使い、
legacy adapter が既存正解データを再利用することを確認する。
tense 不明の `être` や未対応 lemma の `changer` は現在形 quiz へ流さず、
skip / cloze fallback する。

### 品質境界

Phase 3 完了時点で以下が明確であること。

#### deterministic layer が保証すること

- Exercise public DTO に correct answer を含めない
- item type ごとの eligibility と skip reason
- vocabulary / expression の deterministic 生成
- Source evidence からの cloze 再構成
- conjugation の既存動詞 adapter（metadata 不足で présent を推測しない）
- server-side 採点と text normalization
- apostrophe 差は方針どおり許容し、accent 差は無条件許容しない
- 日本語自由記述を完全一致で誤判定しない
- grammar に LLM distractor を自動生成しない
- LearningEvent / LearnerState / ReviewSchedule の記録
- duplicate submit で二重記録しない
- Session 内の同一 `(learning_item_id, exercise_type)` 重複抑止
- unsupported Item の skip reason

#### Phase 3 ではまだ行わないこと

- due / overdue による出題優先
- 「今日の復習」Session
- LLM semantic grading
- FSRS / SM-2 最適化

`skill_direction` と `exercise_version` は LearningEvent.metadata に残す。
`LearnerState.by_direction` の更新は Phase 4（Issue #161）。

## Phase 3 Exit Criteria（Issue #107）との対応

Issue #107 の Phase 3 は、accepted LearningItem から Exercise を生成し、
ユーザーが解き、結果が学習履歴として残ることである。

| Exit Criteria | 満たした実装 | 自動テスト |
|---------------|--------------|------------|
| accepted LearningItem から Exercise を生成できる | `GET /api/tutor/items/{id}/exercises/{type}` | `test_phase3_source_to_practice_to_learning_event_vertical_slice` |
| vocabulary / expression を実際に練習できる | meaning_recognition / ja_to_fr / reconstruction | 同上 / `TutorPhase3Flow.test.tsx` |
| grammar / conjugation は安全な形式のみ生成し、metadata 不足で捏造しない | eligibility + skip reason | 同上 / `test_phase3_conjugation_adapter_reuses_existing_domain` / `test_phase3_exercise_quality_fixture` |
| 同じ LearningItem を recognition / production の両方向で確認できる | Session policy が両方向を混在 | 同上（Session の skill_direction） |
| Source evidence を使った context / cloze 問題を生成できる | source cloze | 同上 / `test_phase3_exercise_quality_fixture` |
| 対応可能な conjugation Item は既存 verb domain を再利用できる | conjugation adapter | `test_phase3_conjugation_adapter_reuses_existing_domain` |
| correct answer を問題提示時に Client へ漏らさない | `PublicExercise` / Session DTO | 同上（`_assert_no_answer_leak`） / `TutorPhase3Flow.test.tsx` |
| 回答を server-side で判定できる | `POST .../answer` | 同上 |
| 回答結果が LearningEvent として保存される | `record_review` | 同上 |
| LearnerState / ReviewSchedule が更新される | 既存パイプライン | 同上 |
| direction / exercise_version が履歴に残る | `exercise_event_metadata` | 同上 |
| Practice Session を複数問連続して完了できる | Practice Session API + UI | 同上 / `TutorPhase3Flow.test.tsx` |
| TTS を Exercise feedback から利用でき、失敗しても学習継続できる | `useTTS` | `TutorPhase3Flow.test.tsx` / `PracticeExerciseCard.test.tsx` |
| DB 再 open 後も学習履歴・状態・予定が残る | file SQLite | `test_phase3_source_to_practice_to_learning_event_vertical_slice` |
| 既存 Source / Candidate / 動詞 / 名詞 / TTS フローに回帰がない | 既存 API は Tutor practice と独立 | `test_phase3_existing_quiz_and_tts_contracts_are_unchanged` / `TutorPhase3Flow.test.tsx` |
| スマホ相当幅で主要操作が実用的である | 全幅ボタン、`minHeight` 44/48、折り返し | `TutorPhase3Flow.test.tsx` |
| `bash scripts/quality-check.sh` が通る | ruff / pytest / lint / frontend test / build | 作業完了時に実行 |
| Phase 3 境界と Phase 4 への引継ぎを記載する | 本セクション | 本ドキュメント |

スマホ実機の使用感は自動 style test だけでは完全代替しない。
実機未確認の場合は PR に残す。

## Phase 4 への引き継ぎ

Phase 4 では Phase 0 から存在する ReviewSchedule と Phase 3 で蓄積した
LearningEvent を使い、以下を実ユーザー体験へ接続する。

- due review queue
- 「今日の復習」Session
- overdue handling
- long-term spacing policy

`LearnerState.by_direction` の recognition / production 別集計は
Issue #161 で実装した。ReviewSchedule の direction 分離は Issue #162。
due review queue API は Issue #163。due queue からの Review Practice Session
は Issue #164。due queue UI は Issue #165。Frontend mastery 表示は後続 Issue。

Phase 3 の Practice Session は手動開始を基本とし、due / mastery による
優先順位付けは Phase 4 へ残す。generic な `/api/tutor/reviews/today` や
recommendation API はまだ持たない。

Phase 4 へ進む前提は、Phase 0〜3 が `bash scripts/quality-check.sh` で
継続して通ることである。

## Phase 4 — recognition / production 別 LearnerState 集計（Issue #161）

Phase 0 からあった `LearnerState.by_direction` を、実際の回答で更新する。
同じ LearningItem について **recognition（見て分かる）** と
**production（自力で出せる）** を独立に集計し、「意味は分かるが自分では
言えない」を区別できることを長期復習の前提にする。

```text
LearningEvent
  -> ExerciseType から SkillDirection を決定
  -> LearnerState 全体を更新
  -> LearnerState.by_direction[direction] を更新
```

実装は既存の `apply_review_event` と `LearningStateService.recompute_learner_state`。
新しい HTTP API は追加しない。Frontend mastery 表示は対象外。

### source of truth

| 使う | 使わない |
|------|----------|
| `SKILL_DIRECTION_BY_EXERCISE_TYPE`（`domain.tutor`） | Client が送った `metadata.skill_direction` |
| `LearningEvent.exercise_type` | direction の推測（未知 type を recognition 等へ割り当てない） |

`domain.exercise.skill_direction_for` は同じ mapping を参照する。
1つの ExerciseType は常に 1つの SkillDirection。

### 全体集計との両立

既存フィールド（`attempt_count` / `correct_count` / `incorrect_count` /
`consecutive_correct` / `last_reviewed_at` / `mastery_score`）は
後方互換のため維持する。1イベントにつき全体と該当 direction の双方を
1回だけ更新する。

### 不変条件

- `by_direction[recognition].attempt_count + by_direction[production].attempt_count`
  は、direction 判定可能な event 件数と一致する
- 同じ event を二重適用しない（既存の duplicate ID 拒否）
- recognition の正答が production の mastery を上げない
- production の誤答が recognition の consecutive_correct を壊さない

### legacy event

- `exercise_type` から mapping できる Phase 3 以前の event は direction 集計へ含める
- mapping できない type は全体集計だけ残し、metadata から direction を推測しない

### スコープ外

- ReviewSchedule の direction 分離（Issue #162）
- due queue / 「今日の復習」
- FSRS / SM-2
- Frontend mastery 表示
- Tutor recommendation

| 観点 | 自動テスト |
|------|------------|
| recognition correct で recognition だけ更新 | `test_apply_review_event_updates_recognition_only_on_recognition_correct` |
| production incorrect で production だけ更新 | `test_apply_review_event_updates_production_only_on_production_incorrect` |
| 全体集計は両方を含む | `test_overall_stats_include_both_directions` |
| recognition / production で異なる mastery | `test_recognition_and_production_have_independent_mastery` |
| 複数 event replay で同じ state | `test_apply_review_event_replay_rebuilds_same_by_direction` / `test_recompute_learner_state_rebuilds_by_direction` |
| duplicate event で二重更新されない | `test_duplicate_event_id_is_rejected_and_does_not_double_apply` |
| legacy event の扱い | `test_legacy_event_updates_overall_but_not_by_direction` |
| DB 再 open 後も by_direction が残る | `test_by_direction_survives_db_reopen` |
| metadata を集計に使わない | `test_skill_direction_for_event_uses_exercise_type_not_metadata` |

## Phase 4 — ReviewSchedule の recognition / production 分離（Issue #162）

LearningItem 単位で 1 件だった `ReviewSchedule` を、
**recognition / production 別に独立管理**する。
「意味は分かるが自分では言えない」Item について、recognition は先送りし
production だけ早めに復習できる。

```text
LearningItem
  ├─ recognition schedule
  └─ production schedule
```

### identity

`(learning_item_id, skill_direction)` で一意。SQLite は複合主キー
（および同内容の unique constraint）で保証する。

### scheduler

初期アルゴリズムは Issue #111 の説明可能な baseline を継続する。

- 初回 / 1 回目正解: 1 日
- 以降の正解: 3 → 7 → 14 日
- 誤答: 1 日に戻す + lapse 増加

間隔の連続正解は `LearnerState.by_direction[direction]` を使う。
全体 LearnerState は維持するが、recognition の回答は production schedule を
進めず、その逆も同様。`scheduler_version` は `v1-directional`。

direction の source of truth は Issue #161 と同じ
`SKILL_DIRECTION_BY_EXERCISE_TYPE`。Client metadata は使わない。

### schema migration

旧 DB の LearningItem 単位 schedule は **根拠なく両方向へ複製しない**。
LearningEvent 履歴が source of truth なので、upgrade 時は
`rebuild_directional_schedules` で event を direction 別に replay して
新 schedule を再構築する。

legacy fallback:

- `exercise_type` から direction を決められない event は推測せず飛ばす
- 履歴が無い Item の旧 schedule は移行後に残さない
- 旧行の interval / review_count は採用しない

### Repository

- `get(item_id, direction)`
- `upsert(schedule)`
- `list_for_item(item_id)`
- `list_due(now, direction optional)`

service / domain は ORM へ直接依存しない。

### 不変条件

- 同一 Item + 同一 direction に schedule は 1 件
- recognition 正答で production の interval / review_count は変わらない
- production 誤答で recognition の lapse_count は増えない
- `due_at` は timezone-aware UTC
- schedule は active LearningItem だけ due 対象

### スコープ外

- FSRS / SM-2
- due queue UI
- personalized interval tuning
- auto mastered 判定

| 観点 | 自動テスト |
|------|------------|
| recognition / production を別々に作成 | `test_same_item_keeps_independent_direction_schedules` / `test_review_schedule_holds_both_directions_and_survives_reopen` |
| recognition 正答のみ interval 延長 | `test_recognition_correct_does_not_extend_production_interval` |
| production 誤答のみ lapse 増加 | `test_production_incorrect_does_not_increase_recognition_lapse` / `test_schedule_after_review_updates_only_matching_direction` |
| 同一 Item に 2 方向を保持 | `test_review_schedule_holds_both_directions_and_survives_reopen` |
| DB 再 open 後も保持 | 同上 |
| schema upgrade で旧 DB を開ける | `test_schema_upgrades_from_v1_and_preserves_existing_rows` / `test_schema_upgrades_from_v2_rebuilds_directional_schedules_from_events` |
| event replay が deterministic | `test_rebuild_directional_schedules_is_deterministic` |
| 旧 schedule を両方向へ複製しない | `test_schema_upgrades_from_v2_rebuilds_directional_schedules_from_events` / `test_rebuild_does_not_use_old_schedule_rows` |
| legacy event を推測しない | `test_rebuild_skips_legacy_events_without_guessing_direction` |
| suspended / mastered 除外 | `test_list_due_excludes_suspended_and_mastered` |
| timezone 境界 | `test_list_due_timezone_boundary_uses_utc` |

## Phase 4 — direction-aware な due review queue（Issue #163）

recognition / production 別の ReviewSchedule から、**今この瞬間に復習期限が
来ている項目**を安定した順序で返す queue を公開する。Phase 4 で初めて
ReviewSchedule をユーザー体験の入口に使うため、単なる DB 検索ではなく、
復習セッションへ渡せる説明可能な contract とする。

```text
ReviewSchedule（due_at <= now, active Item）
  -> recognition / production を別 entry
  -> due_at / learning_item_id / skill_direction で安定ソート
  -> ReviewQueue（entries + summary）
```

実装は `domain.review_queue.build_review_queue` と
`TutorService.list_review_queue`。HTTP は
`GET /api/tutor/reviews/queue`。既存 `GET /api/tutor/reviews/due` の
Phase 0 契約は維持する。

### Queue entry

| フィールド | 内容 |
|------------|------|
| `item` | active な LearningItem |
| `skill_direction` | recognition / production。`review_schedule.skill_direction` と一致 |
| `learner_state` | 当該 Item の現在状態。`by_direction` の該当 stats を含む。未学習なら null |
| `review_schedule` | 当該 direction の予定 |
| `overdue_seconds` / `overdue_days` | `now - due_at`。ちょうど due なら 0 |
| `available_exercise_types` | 当該 direction で出せる ExerciseType。正解は含めない |

### due 判定

- `due_at <= now`
- active LearningItem のみ。suspended / mastered は除外
- recognition / production は別 entry
- `now` は注入可能。HTTP から任意時刻は受け取らない
- ReviewSchedule が無い active Item は due にしない（新規学習とは別概念）

### 並び順

1. `due_at` 昇順（最も overdue なものから）
2. `learning_item_id`
3. `skill_direction`

Phase 5 の personalization score は混ぜない。

### 件数と summary

- `limit` は 1〜100。未指定時は 20。不正値は 422
- 0件は 200 + empty entries / zero summary
- offset / cursor pagination は持たない
- `summary` は limit 適用前の件数（`total_due` / `recognition_due` /
  `production_due` / `overdue_count`）
- `overdue_count` は `due_at < now` の件数

### 異常系

- timezone-naive な `now` は拒否する
- schedule に対応する LearningItem が無い不整合は silent に 200 へ丸めない

### スコープ外

- Review Practice Session 生成（Issue #164）
- 新規 LearningItem との混在
- personalized ranking
- FSRS / SM-2
- Frontend

| 観点 | 自動テスト |
|------|------------|
| due 前は出ない / due 時刻で出る | `test_due_before_now_is_excluded_and_due_at_now_is_included` / `test_list_review_queue_excludes_future_and_includes_due_at_now` |
| overdue 順 | `test_most_overdue_comes_first_then_item_id_then_skill_direction` |
| recognition / production が別 entry | `test_recognition_and_production_are_separate_entries` / `test_review_queue_returns_due_directions_without_now_query` |
| 片方向だけ due | `test_only_due_direction_is_returned` |
| suspended / mastered 除外 | `test_suspended_and_mastered_are_excluded` / `test_review_queue_excludes_suspended_and_mastered` |
| 未スケジュールを due にしない | `test_unscheduled_active_item_is_not_treated_as_due` |
| 0件 | `test_empty_queue_has_zero_summary` / `test_review_queue_empty_returns_zero_summary` |
| limit | `test_limit_truncates_entries_but_summary_counts_all_due` / `test_review_queue_limit_and_invalid_limit` |
| timezone 境界 | `test_timezone_boundary_compares_in_utc` / `test_list_review_queue_timezone_boundary_uses_utc` |
| 安定順 | `test_stable_ordering_is_deterministic` |
| 不整合を silent drop しない | `test_missing_item_for_schedule_is_not_silently_dropped` |
| 既存 due API の回帰なし | `test_due_reviews_returns_overdue_items_without_now_query` / `test_existing_due_api_contract_is_unchanged` |

## Phase 4 — due queue から「今日の復習」Practice Session を生成する（Issue #164）

Phase 3 の手動 Practice Session とは別に、due review queue だけを入力として
**今復習すべきものだけを解く Review Practice Session** を生成する。
新規学習と復習は混ぜない。

```text
due review queue
  -> directionごとのeligible Exercise選択
  -> Review Practice Session
  -> 回答（#149）
  -> direction別state / schedule更新
```

実装は `domain.review_session.build_review_practice_session` と
`ReviewSessionService.create_session`。HTTP は
`POST /api/tutor/review/sessions`。既存の
`POST /api/tutor/practice/sessions` は維持する。

### 入力

| フィールド | 意味 |
|------------|------|
| `question_count` | 上限（default 5 / max 20）。候補が少なければ水増ししない |
| `seed` | 再現用。省略時は `tutor-review`。出題順は overdue 順 |

Source 指定や任意 Item 指定は持たない。due queue が source of truth。
`now` は HTTP から受け取らない。

### Selection policy

1. **due entry のみ** — `due_at <= now` かつ active。schedule の無い Item と
   新規 Item は混ぜない
2. **direction を守る** — recognition due なら recognition Exercise のみ、
   production due なら production Exercise のみ
3. **固定優先順** — personalization score は使わない
   - recognition: `meaning_recognition`
   - production: `cloze`（source evidence がある context 復習）→
     `expression_reconstruction` → `verb_conjugation` → `ja_to_fr`
4. **同一 Item の両方向** — 別 entry として扱い、question_count 上限内で
   overdue 順に含める。同じ `(learning_item_id, exercise_type)` は重複させない
5. **unsupported は skip** — 当該 direction の Exercise を生成できない場合、
   Session 全体を失敗させず `skipped_entries` に理由を返す。
   skip しただけでは ReviewSchedule を更新しない

並びは queue の overdue 順（`due_at` / `learning_item_id` / `skill_direction`）。
overdue 日数が大きくても interval は補正しない。

### 回答後の schedule 更新

Issue #149 の answer pipeline を再利用する。回答した direction だけの
ReviewSchedule を更新する。

- correct → interval 延長
- incorrect → lapse 増加 / 短期化
- 未回答 / skip → schedule 変更なし

### Session 永続化

Phase 3 と同様、Session オブジェクトの DB 永続化はしない。
source of truth は LearningEvent と ReviewSchedule。

### スコープ外

- 新規学習との自動 mix
- mastery / risk ベース ranking
- overdue 補正式
- FSRS / SM-2
- Frontend

| 観点 | 自動テスト |
|------|------------|
| due entry だけ Session へ入る | `test_due_entries_only_enter_the_session` / `test_create_review_session_from_due_queue_only` |
| future / 未スケジュールは入らない | `test_future_entry_is_excluded` / `test_review_session_excludes_future_and_unscheduled` |
| recognition due は recognition Exercise | `test_recognition_due_selects_recognition_exercise` / `test_review_session_keeps_direction` |
| production due は production Exercise | `test_production_due_selects_production_exercise` |
| 両方向 due を別々に扱える | `test_both_directions_are_separate_session_entries` / `test_review_session_handles_both_directions` |
| question_count 上限 | `test_question_count_caps_without_padding` / `test_review_session_question_count_cap` |
| overdue 順 | `test_overdue_order_is_respected` |
| unsupported skip | `test_unsupported_entry_is_skipped_without_failing_session` / `test_review_session_skips_unsupported_entry` |
| skip で schedule が進まない | `test_skip_does_not_advance_schedule` |
| 回答した direction だけ更新 | `test_answering_updates_only_matching_direction` / `test_review_session_answer_updates_only_matching_direction` |
| seed 固定 | `test_same_seed_is_deterministic` / `test_review_session_seed_is_deterministic` |
| due 0件 | `test_empty_queue_returns_empty_session` / `test_review_session_empty_due_queue` |
| Phase 5 を先取りしない | `test_mastery_does_not_reorder_overdue_entries` |

## Phase 4 — 「今日の復習」導線・due件数・Review Session UI（Issue #165）

due queue（Issue #163）と Review Practice Session（Issue #164）を、
Tutor 画面からそのまま開始できる Frontend 体験にする。
新規学習と復習は混ぜない。Phase 3 の Exercise renderer / feedback / TTS は
複製せず再利用する。

```text
Tutor / Home
  -> 今日の復習 N件
  -> 復習を始める
  -> due Exercise を解く
  -> feedback
  -> 次へ
  -> 完了
  -> due 件数を再取得
```

実装:

- API client: `fetchReviewQueue` / `createReviewSession`
- 件数カード: `TutorTodayReviewCard`（`useReviewQueue`）
- Session: `PracticeSessionFlow` の `kind: 'review'`。renderer は
  `PracticeExerciseCard` のまま
- 完了後: `GET /api/tutor/reviews/queue` を再 fetch し、残件数を結果と
  一覧の両方へ反映する。再 fetch 失敗は学習結果を失敗扱いにしない

| 観点 | 自動テスト |
|------|------------|
| due 0件の empty state | `TutorTodayReviewCard.test.tsx` / `TutorPhase4Flow.test.tsx` |
| due 件数 / overdue / direction 要約 | `TutorTodayReviewCard.test.tsx` |
| Review Session 開始 | `TutorFlow.test.tsx` / `TutorPhase4Flow.test.tsx` |
| Phase 3 renderer の再利用 | `PracticeSessionFlow.test.tsx` / `TutorPhase4Flow.test.tsx` |
| 正誤回答と送信失敗時の問題保持 | `TutorPhase4Flow.test.tsx` |
| 完了後 due 件数再 fetch | `TutorPhase4Flow.test.tsx` |
| queue / session 失敗 | `TutorTodayReviewCard.test.tsx` / `PracticeSessionFlow.test.tsx` |
| 通常 Practice / Source 導線の回帰なし | `TutorPhase4Flow.test.tsx` / `TutorPhase3Flow.test.tsx` |
| mobile width | `TutorTodayReviewCard.test.tsx` / `TutorPhase4Flow.test.tsx` |

### スコープ外

- mastery dashboard
- 学習時間予測
- 新規学習と復習の自動 mix
- Tutor recommendation
- 通知 / reminder

## Phase 4 — LearningEvent / LearnerState / ReviewSchedule の原子性と schedule 再構築（Issue #166）

Phase 0 では Event/State と ReviewSchedule を別トランザクションにしていた。
schedule 書き込みだけ失敗すると「履歴は残っているのに due queue へ二度と
現れない」状態が起こり得る。Phase 4 では ReviewSchedule が実ユーザー体験の
入口になるため、**回答記録時の原子性** と **event 履歴からの schedule 再構築**
でこの不整合を閉じる。

```text
回答1件
  -> LearningEvent append
  -> LearnerState upsert
  -> 該当 direction の ReviewSchedule upsert
  （同一トランザクション）

maintenance
  -> LearningEvent 履歴を occurred_at, id 順で replay
  -> direction 別 ReviewSchedule を Item 単位で全置換
```

### 回答記録の原子性

正規経路は `TutorService.record_review`。
`LearningProgressRepository.append_event_upsert_state_and_schedule` が
SQLite の同一 TX で3者を保存する。service は ORM に直接依存しない。

duplicate event ID も同じ TX 内で拒否し、state / schedule を二重適用しない。

### schedule rebuild

履歴が source of truth。旧 schedule 行の interval / review_count は採用しない。
domain の `rebuild_directional_schedules` を `ReviewScheduleRebuilder` が
永続化する。

- `rebuild_for_item(item_id)` — 当該 Item の schedule を同一 TX で全置換
- `rebuild_all()` — Item 単位で順に再構築。1件の失敗が他 Item を中途半端にしない
- direction を復元できない event は推測せず飛ばす

`ReviewScheduleRepository.replace_for_item` が置換の TX 境界。
途中失敗時は既存 schedule を残す。

### 欠損・古い version の検出

`detect_schedule_inconsistencies` / `ReviewScheduleRebuilder.detect_inconsistencies`:

| kind | 意味 |
|------|------|
| `missing_schedule` | 当該 direction の review event があるのに schedule が無い |
| `review_count_mismatch` | 保存済み `review_count` が replay 結果と一致しない |
| `stale_scheduler_version` | `scheduler_version` が現行 `v1-directional` と異なる |
| `unexpected_schedule` | replay 対象でない direction の schedule が残っている |

### 自動修復と明示的 maintenance

| 自動 | 明示的 maintenance に留める |
|------|------------------------------|
| 新規回答の Event/State/Schedule 同一 TX | 欠損 / 旧 version / replay 不一致の検出 |
| duplicate 拒否による二重適用防止 | `rebuild_for_item` / `rebuild_all` |
| | CLI `scripts/rebuild_review_schedules.py`（`--check` / `--item-id` / `--all`） |

アプリ起動時や `GET /api/tutor/reviews/queue` では全履歴 replay しない。
通常経路は保存済み ReviewSchedule を参照する。rebuild は不整合修復用。

### scheduler version

Phase 4 では FSRS へ変更しない。rebuild の対象は #162 の
direction-aware baseline（`v1-directional`）への再計算だけ。
将来アルゴリズムを差し替えるときも、同じ replay 経路で再計算できる。

### スコープ外

- 分散 DB transaction
- event sourcing 基盤の全面刷新
- FSRS / SM-2
- scheduler 自動最適化
- Frontend
- due queue 取得時の replay
- 起動時の自動 rebuild

| 観点 | 自動テスト |
|------|------------|
| event/state/schedule 同一 TX 成功 | `test_record_review_updates_event_state_and_schedule` / `test_append_event_upsert_state_and_schedule_is_atomic` |
| state 失敗で3者 rollback | `test_record_review_state_failure_rolls_back_event_and_schedule` |
| schedule 失敗で3者 rollback | `test_record_review_schedule_failure_rolls_back_event_and_state` / `test_schedule_write_failure_rolls_back_event_and_state` |
| duplicate で3者未変更 | `test_record_review_duplicate_event_id_raises_conflict` / `test_append_event_upsert_state_and_schedule_rejects_duplicate` |
| 欠損 schedule から rebuild | `test_rebuild_from_missing_schedule` |
| recognition だけ欠損 / production だけ欠損 | `test_rebuild_recognition_only_missing_leaves_production` / `test_rebuild_production_only_missing` |
| replay で review_count / lapse / due_at 一致 | `test_rebuild_replay_matches_review_count_lapse_and_due_at` |
| scheduler version 差異の rebuild | `test_rebuild_stale_scheduler_version` |
| rebuild が idempotent | `test_rebuild_is_idempotent` |
| DB 再 open 後の整合性 | `test_rebuild_survives_db_reopen` |
| replace 失敗で中途半端を残さない | `test_replace_for_item_failure_leaves_previous_schedules` |
| due queue が全履歴 replay しない | `test_list_review_queue_uses_stored_schedule_without_replaying_history` |

## Phase 4 vertical slice（Issue #167）

Issue #161〜#166 で追加した direction 別習熟度・direction 別 ReviewSchedule・
due queue・Review Session・Frontend・原子性 / rebuild を、ユーザー操作として
一本につながった vertical slice として検証する。

Phase 4 のゴールは、ユーザーが手動で復習対象を探すのではなく、
**時間経過によって due になった項目が「今日の復習」に現れ、回答後に
次回予定へ進むこと**である。

必須フロー:

```text
1. accepted LearningItemを通常Practiceで学習
2. recognition Exerciseへ回答
3. production Exerciseへ回答
4. LearningEvent / direction別LearnerState / direction別ReviewScheduleが保存される
5. due_atより前は「今日の復習」0件
6. clockを進める
7. recognitionだけdueならrecognition entryだけqueueへ出る
8. productionもdueになれば別entryとして出る
9. Review Sessionを開始
10. due directionに対応するExerciseへ回答
11. correct / incorrectに応じて該当directionのscheduleだけ更新
12. 回答済みentryがqueueから外れる
13. もう片方向のdueは影響を受けない
14. DB再open後もEvent / State / direction Scheduleが残る
```

推奨 fixture は Phase 0〜3 と同じ原文:

```text
Je me suis rendu compte qu'il fallait changer de stratégie.
```

LearningItem 例: `se rendre compte de` / expression / 〜に気づく。
recognition / production の両方を発生させ、別々の schedule で動くことを確認する。
production 側で誤答し、production だけ interval が短縮 / lapse 増加する一方、
recognition schedule は維持される。

clock は注入し、実時間待ちは使わない。due 判定は `due_at <= now`
（timezone-aware UTC）。Frontend の「今日」はユーザー向けラベルであり、
Backend の判定基準ではない。overdue 日数による interval 補正は行わない。

### 品質境界

Phase 4 完了時点で以下が明確であること。

#### deterministic layer が保証すること

- recognition / production 別の LearnerState と ReviewSchedule
- 同じ Item でも片方向だけ due にできる
- `due_at <= now` の active Item だけ due queue へ現れる
- overdue は `due_at` / `learning_item_id` / `skill_direction` の安定順
- suspended / mastered と未スケジュール Item は due にしない
- Review Session は due Item だけから生成し、due direction に合う Exercise だけを出す
- 未回答 / skip では schedule を進めない
- correct / incorrect は該当 direction の schedule だけ更新する
- Event / State / 該当 direction の Schedule は同一トランザクション
- 欠損 / 旧 version の schedule は event 履歴から再構築できる
- duplicate answer で二重更新しない

#### Phase 4 ではまだ行わないこと

- FSRS / SM-2 への移行
- personalized ranking
- 新規学習と復習の自動 mix
- 自動 mastered 判定
- reminder / push notification
- URL / PDF / YouTube ingestion
- source interest / CEFR / mastery / lapse risk を queue 順へ混ぜること

| 観点 | 自動テスト |
|------|------------|
| 学習 → due 前後 → Review Session → 再schedule → DB 再 open | `test_phase4_practice_to_due_review_to_reschedule_vertical_slice` |
| 片方向だけ due / 両方向は別 entry | 同上 |
| production 誤答で recognition を維持 | 同上 |
| clock / timezone / 日付跨ぎ / overdue 古い順 | `test_phase4_clock_timezone_overdue_and_date_boundary` |
| schedule 失敗の rollback と rebuild 後の queue 復帰 | `test_phase4_schedule_write_failure_and_rebuild_returns_to_queue` |
| suspended / mastered / 未schedule / skip / duplicate | `test_phase4_excludes_inactive_unscheduled_duplicate_and_skip` |
| 既存 quiz / TTS / 通常 Practice の回帰 | `test_phase4_existing_quiz_and_tts_contracts_are_unchanged` |
| ranking / today API を先取りしない | `test_phase4_does_not_expose_ranking_or_today_endpoints` |
| Frontend due 件数 / empty / Review Session / 残件 refresh | `TutorPhase4Flow.test.tsx` |
| queue / session 失敗時の状態保持 | 同上 / `PracticeSessionFlow.test.tsx` / `TutorTodayReviewCard.test.tsx` |
| TTS 失敗でも復習を続けられる | `TutorPhase4Flow.test.tsx` / `PracticeExerciseCard.test.tsx` |
| スマホ相当幅 | `TutorPhase4Flow.test.tsx` / `TutorTodayReviewCard.test.tsx` |

## Phase 4 Exit Criteria（Issue #107）との対応

Issue #107 の Phase 4 は、期限が来た項目だけを「今日の復習」として解き、
回答結果が direction 別の学習状態と次回予定へ一貫して残ることである。

| Exit Criteria | 満たした実装 | 自動テスト |
|---------------|--------------|------------|
| recognition / production 別に LearnerState を集計できる | `apply_review_event` の `by_direction` | `test_phase4_practice_to_due_review_to_reschedule_vertical_slice` / `test_apply_review_event_updates_recognition_only_on_recognition_correct` |
| recognition / production 別に ReviewSchedule を保持・更新できる | `(item, direction)` 複合 PK | 同上 / `test_same_item_keeps_independent_direction_schedules` |
| 同じ Item でも片方向だけ due にできる | due queue が direction 別 entry | 同上 / `test_only_due_direction_is_returned` |
| `due_at <= now` の項目だけ due queue へ現れる | `GET /api/tutor/reviews/queue` | 同上 / `test_due_before_now_is_excluded_and_due_at_now_is_included` |
| overdue な項目が deterministic な順で並ぶ | `due_at` / item id / direction | `test_phase4_clock_timezone_overdue_and_date_boundary` |
| suspended / mastered Item は due queue に含まれない | `list_due` が active のみ | `test_phase4_excludes_inactive_unscheduled_duplicate_and_skip` |
| 「今日の復習」Session は due Item だけから生成される | `POST /api/tutor/review/sessions` | `test_phase4_practice_to_due_review_to_reschedule_vertical_slice` |
| due direction に対応した Exercise だけを出す | `REVIEW_EXERCISE_PRIORITY` | 同上 |
| 未回答 / skip では schedule を進めない | Session 組み立ては schedule を書かない | `test_phase4_excludes_inactive_unscheduled_duplicate_and_skip` |
| correct / incorrect で該当 direction の次回 schedule が更新される | `record_review` | `test_phase4_practice_to_due_review_to_reschedule_vertical_slice` |
| もう片方向の state / schedule を誤って更新しない | direction 別 previous schedule | 同上 |
| 回答後に LearningEvent / LearnerState / ReviewSchedule が一貫して保存される | 同一 TX | 同上 / `test_phase4_schedule_write_failure_and_rebuild_returns_to_queue` |
| schedule 欠損・旧 version を event 履歴から再構築できる | `ReviewScheduleRebuilder` | 同上 |
| DB 再 open 後も long-term review 状態が保持される | file SQLite | `test_phase4_practice_to_due_review_to_reschedule_vertical_slice` |
| Tutor UI で due 件数を確認し Review Session を完了できる | `TutorTodayReviewCard` + `PracticeSessionFlow` | `TutorPhase4Flow.test.tsx` |
| due 0件の自然な empty state がある | empty copy + 開始ボタン非表示 | 同上 / `TutorTodayReviewCard.test.tsx` |
| 既存 Source / Candidate / 通常 Practice / 動詞 / 名詞 / TTS に回帰がない | 既存 API は独立 | `test_phase4_existing_quiz_and_tts_contracts_are_unchanged` / `TutorPhase4Flow.test.tsx` |
| スマホ相当幅で主要操作が実用的である | 全幅ボタン、`minHeight` 44/48 | `TutorPhase4Flow.test.tsx` / `TutorTodayReviewCard.test.tsx` |
| `bash scripts/quality-check.sh` が通る | ruff / pytest / lint / frontend test / build | 作業完了時に実行 |
| Phase 4 境界と Phase 5 への引継ぎを記載する | 本セクション | 本ドキュメント |

スマホ実機の使用感は自動 style test だけでは完全代替しない。
実機未確認の場合は PR に残す。

## Phase 5 への引き継ぎ

Phase 4 で「期限が来たものを復習する」deterministic な loop を完成させる。

Phase 5 ではこの土台の上で初めて、以下を使って **何を優先して学ぶか** を決める。

- source interest / recency
- CEFR level fit
- mastery
- lapse risk
- recent error pattern
- recognition / production imbalance
- 新規学習と復習の配分

Phase 4 ではこれらを ranking へ混ぜない。generic な
`/api/tutor/reviews/today` や recommendation API は持たない。
due queue の並びは overdue 順のまま維持する。

Phase 5 へ進む前提は、Phase 0〜4 が `bash scripts/quality-check.sh` で
継続して通ることである。

## Phase 1 Exit Criteria（Issue #107）との対応

Issue #107 の Phase 1 は、ユーザーがフランス語テキストを貼り付け、
SourceDocument として保存・参照できる最小 UI/API である。

| Exit Criteria | 満たした実装 | 自動テスト |
|---------------|--------------|------------|
| ユーザーがフランス語本文を手動貼り付けできる | `TutorSourceForm` の textarea | `TutorPhase1Flow.test.tsx` |
| title / optional note とともに SourceDocument として保存できる | `POST /api/tutor/sources` + `metadata.note` | `test_phase1_text_ingestion_vertical_slice` |
| 保存済み Source 一覧を見られる | `GET /api/tutor/sources` / `TutorSourceList` | 同上 / `TutorSourceList.test.tsx` |
| Source 詳細で原文全文を読める | `GET /api/tutor/sources/{source_id}` / `TutorSourceDetail` | 同上 / `TutorSourceDetail.test.tsx` |
| アプリ/DB 再 open 後も保存内容が残る | SQLite file DB + Frontend 再マウント | 同上 / `TutorPhase1Flow.test.tsx` |
| empty/loading/error/404 の主要状態が扱われている | list / detail status | `TutorPhase1Flow.test.tsx` |
| 既存の動詞・名詞・冠詞・TTS学習フローに回帰がない | quiz/TTS API は Tutor ingestion と独立 | `test_phase1_existing_quiz_and_tts_contracts_are_unchanged` / `App.test.tsx` |
| Phase 1 では LLM 非依存である | Tutor API / service / domain に LLM import なし | `test_phase1_tutor_modules_are_llm_independent` |
| URL/PDF/YouTube 等の入力を含めていない | `SourceType=manual_text` のみ | `test_phase1_has_no_url_pdf_youtube_ingestion_endpoints` |
| スマホ相当幅で主要操作に問題がない | 本文 `minHeight: 40vh`、折り返し、全幅ボタン | `TutorPhase1Flow.test.tsx` / 各コンポーネントの style 検証 |

Phase 2 以降へ進む前提は、Phase 0 と Phase 1 が
`bash scripts/quality-check.sh` で継続して通ることである。
Phase 2 自体の完了条件と Phase 3 への引継ぎは、上記
「Phase 2 Exit Criteria」と「Phase 3 への引き継ぎ」を正とする。
Phase 3 自体の完了条件と Phase 4 への引継ぎは、上記
「Phase 3 Exit Criteria」と「Phase 4 への引き継ぎ」を正とする。
`by_direction` 集計の source of truth は上記
「Phase 4 — recognition / production 別 LearnerState 集計」を正とする。
ReviewSchedule の direction 分離は上記
「Phase 4 — ReviewSchedule の recognition / production 分離」を正とする。
due review queue は上記
「Phase 4 — direction-aware な due review queue」を正とする。
Review Practice Session は上記
「Phase 4 — due queue から「今日の復習」Practice Session を生成する」を正とする。
「今日の復習」Frontend は上記
「Phase 4 — 「今日の復習」導線・due件数・Review Session UI」を正とする。
Event / State / Schedule の原子性と schedule 再構築は上記
「Phase 4 — LearningEvent / LearnerState / ReviewSchedule の原子性と schedule 再構築」を正とする。
Phase 4 自体の完了条件と Phase 5 への引継ぎは、上記
「Phase 4 Exit Criteria」と「Phase 5 への引き継ぎ」を正とする。

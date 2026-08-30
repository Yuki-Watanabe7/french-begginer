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
Exercise の server-side 採点と LearningEvent 記録（Issue #149）
の責務分離・不変条件を記録する。

- ドメイン: `backend/app/domain/tutor.py` / `backend/tests/test_tutor_domain.py`
- 永続化: `backend/app/repositories/` / `backend/app/persistence/`
  / `backend/tests/test_tutor_persistence.py`
- 状態更新: `backend/app/services/learning_state_service.py`
  / `backend/tests/test_learning_state_service.py`
- 復習予定: `backend/app/domain/review_scheduler.py`
  / `backend/app/services/review_service.py`
  / `backend/tests/test_review_scheduler.py`
  / `backend/tests/test_review_service.py`
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
| `ReviewSchedule` | 次にいつ復習するか | 上書き更新される |

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
別々に追跡できる構造にしてある。

Phase 0では `by_direction` は空のままでよく、集計ロジックは後続Issueで実装する。
「高度な能力モデルを今作る」のではなく、**後から入れられる形にしておく**のが目的。

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
| `LearningProgressRepository` | append_event_and_upsert_state | event と state を同一トランザクション |
| `ReviewScheduleRepository` | get / upsert / list_due | LearningItem につき1件（PK） |

SQLite 実装の入口は `TutorSqliteStore`。
接続先は `TUTOR_DATABASE_URL`、未指定時は `backend/data/tutor.db`。
テストは `TutorSqliteStore.in_memory()` または temporary file URL を使う。

### データ整合性

- `LearningEvent` / `LearnerState` / `ReviewSchedule` は存在する
  `LearningItem` を参照する（FK + repository 側の存在チェック）
- `LearningItemCandidate` は存在する `SourceDocument` を参照する
  （FK + repository 側の存在チェック）
- `LearnerState` と `ReviewSchedule` は `learning_item_id` を主キーにし、1件に制限する
- `ON DELETE RESTRICT` により、履歴がある LearningItem を SQL から消しても失敗する
- repository に `delete` を置かない（履歴消失を安易に許可しない）
- 日時は timezone-aware のみ受け付け、UTC の ISO 8601
  （`YYYY-MM-DDTHH:MM:SS.ffffff+00:00`）で保存する。
  この形式なら文字列比較が時系列順と一致し、`due_at <= now` を SQL で判定できる

### トランザクションの保証範囲

`TutorService.record_review` は次の2段階で書き込む。

1. **LearningEvent と LearnerState** — `LearningProgressRepository.append_event_and_upsert_state`
   が同一トランザクションで保存する。state 書き込み失敗時は event も残らない
   （`test_state_upsert_failure_rolls_back_event`）。重複 event ID も
   このトランザクションで拒否し、state を二重適用しない。
2. **ReviewSchedule** — event/state 確定後に `ReviewService.schedule_after_review`
   が別トランザクションで upsert する。schedule 書き込みが失敗しても
   event/state は残る（`test_schedule_write_failure_leaves_event_and_state`）。

Phase 0 では event / state / schedule 三者の完全な原子性は保証しない。
schedule が欠けた場合、LearnerState と LearningEvent 履歴から再計算できる。
`review_count` は previous schedule に依存するため、欠けた状態で次の
review を入れると 1 から再カウントされる。三者を1トランザクションに
閉じるのは後続Issueの対象とする。

### schema versioning

`schema_migrations` テーブルが適用済み version を保持する。

1. version 0（未初期化）: `create_all` で現行スキーマを作り version 2 を記録する
2. version < 現行: `UPGRADE_STEPS` の upgrade 関数を順に適用する
3. version > 現行: `SchemaVersionError`（新しいDBを古いコードで開いた）

現行 version は `2`。version 2 の upgrade は `learning_item_candidates`
テーブルを追加する（Issue #131）。新規DBは `create_all` で version 2 を直接作る。

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

Phase 0 では `by_direction`（recognition / production）は更新しない。
`exercise_type` は LearningEvent に必ず残し、後続Issueで能力を分離する。

### 不整合への備え

LearnerState は LearningEvent のキャッシュである。event と state の
書き込みは同一トランザクションだが、万一 state だけ欠けた場合は
`LearningStateService.recompute_learner_state` が履歴を `occurred_at, id`
順に畳み込んで state を再構築できる。

## 復習スケジューラ（Issue #111）

`schedule_next_review(state, event, previous_schedule)` が次の
ReviewSchedule を決める。更新ルール自体は domain の純関数に置き、
service は存在確認と永続化、due 取得を担う。

```text
LearnerState（当該event適用後）と LearningEvent
  -> schedule_next_review で次予定を算出
  -> ReviewSchedule を upsert
  -> list_due(now) で due_at <= now かつ active の項目を取得
```

`datetime.now()` は domain からも service からも呼ばない。
due 算出の基準は `event.occurred_at`、due 取得の基準は引数 `now`。

### 初期スケジューリング方針

Phase 0 では SM-2 / FSRS は導入しない。日数の最適性は狙わず、
後からアルゴリズムを差し替えられる **単純・deterministic・説明可能な
baseline** にする。同じ (state, event, previous_schedule) からは
常に同じ ReviewSchedule になる。

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
- `scheduler_version` は現行アルゴリズムの版（`v0`）を書き込む
- 過去の schedule 履歴は残さず、現行予定だけを上書きする

### due 取得

`ReviewScheduleRepository.list_due(now)` / `ReviewService.list_due(now)`:

- `due_at <= now` の予定だけ返す
- **active な LearningItem のみ**。`suspended`（ユーザーが一時除外）と
  `mastered`（定着済み）は、予定が残っていても出題対象にしない。
  schedule 自体は消さないので、status を active に戻せば再開できる
- 返却順は `due_at` 昇順、同じ due_at なら `learning_item_id` 昇順

### 将来拡張への備え

- `scheduler_version` でアルゴリズムを識別する
- 間隔計算（domain）と due query（repository）を分離している
- Phase 4 で SM-2 / FSRS 等と比較・移行できる
- 過去 schedule を再計算して履歴を書き換える設計にはしない

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

`GET /api/tutor/reviews/due` は任意時刻を HTTP query から受け取らない。
due 判定の基準はサーバー時刻（`utcnow`）。テストでは `TutorService` の
`clock` 注入、または過去の `occurred_at` で due を作る。

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
| schedule 書き込み失敗時の保証 | `test_schedule_write_failure_leaves_event_and_state` |
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
| 学習イベント記録 | `TutorService.record_review` → `LearningStateService.record_event` | `test_vertical_slice_source_to_due_to_rereview` / `test_review_persists_event_and_updates_state_and_schedule` |
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
Phase 2 では LearningItem を作れるところまでで止め、
以下はまだ行わない。

- Frontend session UI
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

Phase 0 と同様、`LearnerState.by_direction` の更新はこの Issue では行わない。

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

### Phase 3 の残り（#145 / #146 / #147 / #148 のスコープ外、#149 で一部実施）

- Frontend session UI
- by_direction の更新
- due review session（Phase 4）

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

Frontend session UI は対象外。LLM semantic grading は行わない。

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
Phase 3 では `LearnerState.by_direction` は更新しない。

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

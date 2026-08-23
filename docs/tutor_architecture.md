# Tutor Architecture

関心ベースの個人フランス語家庭教師機能（Roadmap: Issue #107）の設計ドキュメント。

このドキュメントは Phase 0 の中核ドメインモデル（Issue #108）、
永続化層（Issue #109）、学習状態更新（Issue #110）、
初期 Review Scheduler（Issue #111）、最小 API（Issue #112）、
vertical slice 統合テスト（Issue #113）、
Phase 1 の Source 一覧 API（Issue #121）、Frontend 型と API client（Issue #122）、
手入力保存画面（Issue #123）、一覧・詳細画面（Issue #124）、
および Phase 1 vertical slice（Issue #125）の責務分離・不変条件を記録する。

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
- 統合: `backend/tests/test_tutor_vertical_slice.py`
  / `backend/tests/test_tutor_phase1_vertical_slice.py`
  / `frontend/src/test/TutorPhase1Flow.test.tsx`

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

Phase 0時点では `backend/app/domain/conjugation.py` /
`backend/app/domain/noun.py` に一切変更を加えていない（破壊的変更なし）。

## LLM境界

- Phase 0 は LLM 非依存。Source / LearningItem は手入力またはテスト fixture で与える
- Phase 1 も LLM 非依存。ユーザーが貼り付けた本文を SourceDocument として保存・表示するだけ
- Phase 2 で Source から LearningItem 候補を生成する
- LLM 生成結果は正規化・ validation 後に domain へ入れる。出力をそのまま正解データにしない

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

1. version 0（未初期化）: `create_all` で現行スキーマを作り version 1 を記録する
2. version < 現行: `UPGRADE_STEPS` の upgrade 関数を順に適用する
3. version > 現行: `SchemaVersionError`（新しいDBを古いコードで開いた）

Phase 0 の現行 version は `1`。`UPGRADE_STEPS` は空である。
次の破壊的変更時に version 2 の upgrade 関数を追加する。

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

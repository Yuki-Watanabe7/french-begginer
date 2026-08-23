# Tutor Architecture

関心ベースの個人フランス語家庭教師機能（Roadmap: Issue #107）の設計ドキュメント。

このドキュメントは Phase 0 の中核ドメインモデル（Issue #108）と
永続化層（Issue #109）の責務分離・不変条件を記録する。

- ドメイン: `backend/app/domain/tutor.py` / `backend/tests/test_tutor_domain.py`
- 永続化: `backend/app/repositories/` / `backend/app/persistence/`
  / `backend/tests/test_tutor_persistence.py`

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

**Source は「触れた素材」、LearningItem は「覚える対象」であり、粒度も
ライフサイクルも異なる。**

- 1つのSourceから複数のLearningItemが生まれる（1対多）
- 同じ表現（例: `il s'agit de`）が複数のSourceに現れても、
  LearningItemは1件に正規化し、出典を `source_refs` に積み増す（多対多）
- Sourceを削除・非表示にしても、すでに学習中のLearningItemの習熟は失われない
- Sourceは原文の保存が責務であり、意味・難易度・学習状態を持たない

このため `LearningItem.source_refs: list[SourceRef]` という参照リストを持ち、
Sourceの本文をLearningItem側にコピーしない。

### 2. LearningEvent と LearnerState を分ける

**LearningEvent は「起きた事実の履歴」、LearnerState は「現在の状態」。**

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

`SourceRef` は Phase 2（LLM抽出）に備えて `evidence_span` と `confidence` を
optionalで持てる形にしてある。LLMの出力は必ずこの型付きデータへ正規化し、
「原文のどこを根拠にしたか」「どれくらい確信があるか」を保持する。

Phase 0ではどちらも `None` のままでよい。

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

`ExerciseType` には既存の学習モード（`verb_conjugation` / `noun_gender` /
`noun_article`）を含めてある。既存の動詞・名詞クイズの結果も
`LearningEvent` として記録できる方向へ段階的に接続する想定。

Phase 0時点では `backend/app/domain/conjugation.py` /
`backend/app/domain/noun.py` に一切変更を加えていない（破壊的変更なし）。

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

### schema versioning

`schema_migrations` テーブルが適用済み version を保持する。

1. version 0（未初期化）: `create_all` で現行スキーマを作り version 1 を記録する
2. version < 現行: `UPGRADE_STEPS` の upgrade 関数を順に適用する
3. version > 現行: `SchemaVersionError`（新しいDBを古いコードで開いた）

Phase 0 の現行 version は `1`。`UPGRADE_STEPS` は空である。
次の破壊的変更時に version 2 の upgrade 関数を追加する。

ローカルで生成される `*.db` は git 管理対象外（`.gitignore`）。

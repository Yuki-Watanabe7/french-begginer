"""スキーマ初期化とバージョン管理。

Phase 0 では Alembic を導入せず、`schema_migrations` テーブルで現行バージョン
を記録する。初期スキーマは SQLAlchemy の `create_all` で作成し、以降の
破壊的変更は `UPGRADE_STEPS` に upgrade 関数を追加して適用する。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from pydantic import ValidationError
from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection, Engine

from app.domain.review_scheduler import rebuild_directional_schedules
from app.domain.tutor import LearningEvent, utcnow
from app.persistence.datetime_codec import dump_utc, load_utc
from app.persistence.models import (
    Base,
    LearningEventRow,
    LearningItemCandidateRow,
    ReviewScheduleRow,
    SchemaMigrationRow,
)

CURRENT_SCHEMA_VERSION = 3

UpgradeFn = Callable[[Connection], None]


class SchemaVersionError(RuntimeError):
    """DBのschema versionがこのコードと互換でない。"""


def get_schema_version(engine: Engine) -> int:
    with engine.connect() as conn:
        if not _has_schema_migrations(conn):
            return 0
        return _read_version(conn)


def init_schema(engine: Engine) -> None:
    """未初期化なら現行スキーマを作成し、古いDBなら upgrade を適用する。"""
    with engine.begin() as conn:
        SchemaMigrationRow.__table__.create(conn, checkfirst=True)
        version = _read_version(conn)
        if version == 0:
            Base.metadata.create_all(conn)
            _record_version(conn, CURRENT_SCHEMA_VERSION)
            return
        if version > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"DBのschema version ({version}) がコードの現行version "
                f"({CURRENT_SCHEMA_VERSION}) より新しい。"
                "アプリケーションを更新する必要がある"
            )
        _apply_upgrades(conn, version)


def _has_schema_migrations(conn: Connection) -> bool:
    return conn.dialect.has_table(conn, SchemaMigrationRow.__tablename__)


def _read_version(conn: Connection) -> int:
    value = conn.execute(select(SchemaMigrationRow.version)).scalars().all()
    return max(value, default=0)


def _record_version(conn: Connection, version: int) -> None:
    conn.execute(
        insert(SchemaMigrationRow).values(
            version=version,
            applied_at=dump_utc(utcnow()),
        )
    )


def _apply_upgrades(conn: Connection, from_version: int) -> None:
    for version, upgrade in UPGRADE_STEPS:
        if version <= from_version:
            continue
        upgrade(conn)
        _record_version(conn, version)


def _upgrade_to_2(conn: Connection) -> None:
    """Phase 2: LearningItemCandidate テーブルを追加する。"""
    LearningItemCandidateRow.__table__.create(conn)


def _upgrade_to_3(conn: Connection) -> None:
    """Phase 4: ReviewSchedule を (item, direction) 別に再構築する.

    旧 schedule 行はコピーしない。LearningEvent 履歴を direction 別に
    replay した結果だけを残す。direction を復元できない event は推測せず飛ばす。
    """
    conn.execute(text("ALTER TABLE review_schedules RENAME TO review_schedules_legacy"))
    conn.execute(text("DROP INDEX IF EXISTS ix_review_schedules_due_at"))
    ReviewScheduleRow.__table__.create(conn)
    _rebuild_review_schedules_from_events(conn)
    conn.execute(text("DROP TABLE review_schedules_legacy"))


def _rebuild_review_schedules_from_events(conn: Connection) -> None:
    event_table = LearningEventRow.__table__
    rows = conn.execute(
        select(event_table).order_by(
            event_table.c.learning_item_id,
            event_table.c.occurred_at,
            event_table.c.id,
        )
    ).mappings()

    by_item: dict[str, list[LearningEvent]] = defaultdict(list)
    for row in rows:
        by_item[row["learning_item_id"]].append(_learning_event_from_db_row(row))

    schedule_table = ReviewScheduleRow.__table__
    for events in by_item.values():
        for schedule in rebuild_directional_schedules(events).values():
            conn.execute(
                schedule_table.insert().values(
                    learning_item_id=schedule.learning_item_id,
                    skill_direction=schedule.skill_direction,
                    due_at=dump_utc(schedule.due_at),
                    interval_days=schedule.interval_days,
                    review_count=schedule.review_count,
                    lapse_count=schedule.lapse_count,
                    scheduler_version=schedule.scheduler_version,
                    metadata_json=schedule.metadata,
                )
            )


def _learning_event_from_db_row(row: dict[str, object]) -> LearningEvent:
    payload = {
        "id": row["id"],
        "learning_item_id": row["learning_item_id"],
        "event_type": row["event_type"],
        "exercise_type": row["exercise_type"],
        "result": row["result"],
        "occurred_at": load_utc(str(row["occurred_at"])),
        "response_time_ms": row["response_time_ms"],
        "metadata": row["metadata_json"] or {},
    }
    try:
        return LearningEvent.model_validate(payload)
    except ValidationError:
        return LearningEvent.model_construct(**payload)


# (target_version, upgrade) 。初期スキーマは create_all で作るため、
# 新規DBは version 3 として作成される。既存の version 1/2 DB は upgrade する。
UPGRADE_STEPS: list[tuple[int, UpgradeFn]] = [
    (2, _upgrade_to_2),
    (3, _upgrade_to_3),
]

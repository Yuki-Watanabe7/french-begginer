"""スキーマ初期化とバージョン管理。

Phase 0 では Alembic を導入せず、`schema_migrations` テーブルで現行バージョン
を記録する。初期スキーマは SQLAlchemy の `create_all` で作成し、以降の
破壊的変更は `UPGRADE_STEPS` に upgrade 関数を追加して適用する。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine

from app.domain.tutor import utcnow
from app.persistence.datetime_codec import dump_utc
from app.persistence.models import Base, SchemaMigrationRow

CURRENT_SCHEMA_VERSION = 1

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


# (target_version, upgrade) 。初期スキーマは create_all で作るためここは空。
# 次の破壊的変更時に 2 以降を追加する。
UPGRADE_STEPS: list[tuple[int, UpgradeFn]] = []

"""SQLAlchemy engine の生成。SQLite では FK を有効化する。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import StaticPool

from app.persistence.config import get_database_url, is_production
from app.persistence.schema import init_schema


def create_db_engine(database_url: str | None = None) -> Engine:
    url = get_database_url(database_url)
    if is_production():
        from app.persistence.production import check_production_database

        path = check_production_database()
    else:
        _ensure_sqlite_parent_dir(url)

    kwargs: dict[str, object] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if is_production():
            # 確認後にファイルが消えた場合も SQLite に新規作成させない。
            kwargs["creator"] = lambda: sqlite3.connect(
                f"{path.as_uri()}?mode=rw", uri=True, check_same_thread=False
            )
        if _is_sqlite_memory(url):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_initialized_engine(database_url: str | None = None) -> Engine:
    engine = create_db_engine(database_url)
    init_schema(engine)
    return engine


def _is_sqlite_memory(url: str) -> bool:
    parsed = make_url(url)
    return parsed.get_backend_name() == "sqlite" and parsed.database in (
        None,
        ":memory:",
    )


def _ensure_sqlite_parent_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database = parsed.database
    if not database or database == ":memory:":
        return
    Path(database).parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

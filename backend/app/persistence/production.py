"""本番 DB の明示初期化と、空 DB への意図しない切替の防止（#220）。"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine

from app.persistence.config import DEFAULT_DB_FILENAME, get_database_url, is_production
from app.persistence.schema import init_schema

PRODUCTION_UID = 10001
PRODUCTION_GID = 10001


def check_production_directory() -> Path:
    if not is_production():
        raise ValueError("APP_ENV=production のコンテナ内で実行してください")
    from sqlalchemy.engine.url import make_url

    path = Path(str(make_url(get_database_url()).database))
    directory = path.parent
    info = directory.stat()  # mkdir しない。mount/所有権不足は停止する。
    if directory.is_symlink() or path.is_symlink():
        raise ValueError("本番 DB に symlink は使えません")
    if (os.geteuid(), os.getegid()) != (PRODUCTION_UID, PRODUCTION_GID):
        raise ValueError("本番 DB は uid/gid 10001:10001 で操作してください")
    if (info.st_uid, info.st_gid) != (PRODUCTION_UID, PRODUCTION_GID):
        raise ValueError("本番 DB ディレクトリの所有者が 10001:10001 ではありません")
    if info.st_mode & 0o077:
        raise ValueError("本番 DB ディレクトリの権限を 0700 にしてください")
    # DB 本体だけでなく journal/WAL を作るディレクトリの権限も確認する。
    with tempfile.TemporaryFile(dir=directory):
        pass
    return path


def check_production_database() -> Path:
    path = check_production_directory()
    if not path.is_file():
        raise ValueError(
            "本番 DB がありません。初回のみ明示初期化し、既存環境は復元してください"
        )
    with closing(
        sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=5)
    ) as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
            0
        ]
        if not version:
            raise ValueError("本番 DB の schema version がありません")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("CREATE TABLE production_write_probe (id INTEGER)")
        finally:
            conn.rollback()
    return path


def initialize() -> None:
    path = check_production_directory()
    # 既存 DB は空でも上書きしない。失敗ファイルも調査のため保持する。
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    try:
        init_schema(engine)
    finally:
        engine.dispose()
    check_production_database()


def main() -> int:
    if sys.argv[1:] != ["initialize-empty-volume"]:
        print("usage: python -m app.persistence.production initialize-empty-volume")
        return 2
    try:
        initialize()
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"初期化失敗（既存 DB は上書きしません）: {exc}", file=sys.stderr)
        return 1
    print(f"{DEFAULT_DB_FILENAME}: 初回初期化・書込確認済み")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

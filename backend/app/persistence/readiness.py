"""Tutor DB の readiness 確認（Issue #219）。

`GET /health` はプロセスの応答だけを返す。DB が開けて書けるかはここで確かめる。
本番の healthcheck と runbook から CLI として呼ぶ:

  python -m app.persistence.readiness          # 結果を表示。失敗なら exit 1

既存 DB だけを対象にし、ファイルやディレクトリを作らない（空 DB へ黙って切り替えない）。
書込確認は rollback する一時テーブル作成で行い、学習データは変更しない。
HTTP には公開しない（パスを応答に載せない）。
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine.url import make_url

from app.persistence.config import get_database_url
from app.persistence.schema import CURRENT_SCHEMA_VERSION


@dataclass(frozen=True)
class DatabaseReadiness:
    ready: bool
    detail: str
    path: Path | None = None
    schema_version: int | None = None


def check_database_readiness(database_url: str | None = None) -> DatabaseReadiness:
    url = make_url(get_database_url(database_url))
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return DatabaseReadiness(False, "file-based SQLite ではない")

    path = Path(url.database)
    try:
        exists = path.is_file()
    except OSError as exc:
        return DatabaseReadiness(False, f"DB の場所にアクセスできない: {exc}", path)
    if not exists:
        return DatabaseReadiness(False, "DB ファイルがない（未初期化）", path)

    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=5
        )
    except sqlite3.Error as exc:
        return DatabaseReadiness(False, f"DB を開けない: {exc}", path)
    try:
        conn.isolation_level = None
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            detail = f"quick_check が ok でない: {integrity}"
            return DatabaseReadiness(False, detail, path)
        version = _schema_version(conn)
        if version != CURRENT_SCHEMA_VERSION:
            detail = f"schema version {version} がコードの版と異なる"
            return DatabaseReadiness(False, detail, path, version)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("CREATE TABLE readiness_probe (id INTEGER)")
        finally:
            conn.execute("ROLLBACK")
    except sqlite3.Error as exc:
        return DatabaseReadiness(False, f"DB に書き込めない: {exc}", path)
    finally:
        conn.close()
    return DatabaseReadiness(True, "ok", path, version)


def _schema_version(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("schema_migrations",),
    ).fetchone()
    if has_table is None:
        return 0
    return conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0


def main(argv: list[str] | None = None) -> int:
    quiet = "--quiet" in (sys.argv[1:] if argv is None else argv)
    result = check_database_readiness()
    if not quiet or not result.ready:
        status = "ready" if result.ready else "not ready"
        print(
            f"{status}: {result.detail} "
            f"(path={result.path}, schema_version={result.schema_version})",
            file=sys.stdout if result.ready else sys.stderr,
        )
    return 0 if result.ready else 1


if __name__ == "__main__":
    sys.exit(main())

"""SQLite backup API による整合コピーと私的 manifest。HTTP には公開しない。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.persistence.models import Base
from app.persistence.schema import CURRENT_SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_database(path: Path) -> dict:
    """読み取りだけ。旧版も検査し、ここでは migration を実行しない。"""
    with closing(
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    ) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("integrity_check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign_key_check failed")
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
            0
        ]
        if not isinstance(version, int) or not 1 <= version <= CURRENT_SCHEMA_VERSION:
            raise ValueError("unsupported schema version")
        counts = {}
        for name, table in Base.metadata.tables.items():
            if (name == "learning_item_candidates" and version < 2) or (
                name.startswith("known_item_") and version < 5
            ):
                continue
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')}
            expected = {c.name for c in table.columns}
            if name == "source_documents" and version < 4:
                expected -= {
                    "content_hash",
                    "ingestion_version",
                    "canonical_locator",
                    "provenance_json",
                    "segments_json",
                }
            if name == "review_schedules" and version < 3:
                expected -= {"skill_direction"}
            if not expected <= columns:
                raise ValueError(f"schema columns missing: {name}")
            primary_key = {c.name for c in table.primary_key.columns}
            if name == "review_schedules" and version < 3:
                primary_key -= {"skill_direction"}
            actual_key = {
                row[1] for row in conn.execute(f'PRAGMA table_info("{name}")') if row[5]
            }
            if actual_key != primary_key:
                raise ValueError(f"schema primary key mismatch: {name}")
            foreign_keys = {
                (fk.parent.name, fk.column.table.name, fk.column.name)
                for fk in table.foreign_keys
            }
            actual_fk = {
                (row[3], row[2], row[4])
                for row in conn.execute(f'PRAGMA foreign_key_list("{name}")')
            }
            if not foreign_keys <= actual_fk:
                raise ValueError(f"schema foreign keys missing: {name}")
            counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        directions = {}
        if version >= 3:
            directions = dict(
                conn.execute(
                    "SELECT skill_direction, COUNT(*) FROM review_schedules "
                    "GROUP BY skill_direction"
                ).fetchall()
            )
            if set(directions) - {"recognition", "production"}:
                raise ValueError("unknown review direction")
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        schema_hash = hashlib.sha256(json.dumps(schema).encode()).hexdigest()
    return {
        "schema_version": version,
        "schema_sha256": schema_hash,
        "counts": counts,
        "review_directions": directions,
        "database_bytes": path.stat().st_size,
        "database_sha256": sha256(path),
    }


def snapshot(source: Path, destination: Path, *, timeout: float = 60) -> None:
    """書込中も整合コピー。失敗時はこの呼出で作ったファイルだけを除去する。"""
    if not source.is_file() or source.is_symlink():
        raise ValueError("source DB missing or symlink")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    deadline = time.monotonic() + timeout

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup timed out")

    try:
        with (
            closing(
                sqlite3.connect(
                    f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=5
                )
            ) as reader,
            closing(sqlite3.connect(destination)) as writer,
        ):
            reader.backup(writer, pages=128, progress=progress, sleep=0.05)
            # WAL 元でも単独 DB として復元できる状態にする。
            writer.execute("PRAGMA journal_mode=DELETE")
        inspect_database(destination)
        with destination.open("rb") as stream:
            os.fsync(stream.fileno())
    except BaseException:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        raise


def create_archive(
    source: Path,
    output: Path,
    *,
    app_commit: str,
    reason: str,
    app_dirty: bool = False,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", app_commit):
        raise ValueError("app commit must be a full Git SHA")
    started = utc_now()
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        directory = Path(temp)
        db = directory / "tutor.db"
        snapshot(source, db)
        manifest = {
            "format_version": 1,
            "backup_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex,
            "snapshot_started_at": started,
            "snapshot_completed_at": utc_now(),
            "app_commit": app_commit,
            "app_dirty": app_dirty,
            "reason": reason,
            "runtime": {
                "uid": 10001,
                "gid": 10001,
                "data_dir": "/var/lib/french-tutor",
                "workers": 1,
            },
            **inspect_database(db),
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with (
            output.open("xb") as stream,
            tarfile.open(fileobj=stream, mode="w") as archive,
        ):
            for name in ("tutor.db", "manifest.json"):
                archive.add(directory / name, arcname=name)
    output.chmod(0o600)
    return manifest


def unpack_verified(archive_path: Path, directory: Path) -> dict:
    """固定2ファイルだけを読む。パス移動・symlink・重複 entry は拒否。"""
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        if {m.name for m in members} != {"tutor.db", "manifest.json"} or len(
            members
        ) != 2:
            raise ValueError("unexpected backup archive members")
        for member in members:
            if not member.isfile():
                raise ValueError("backup member is not a regular file")
            with (
                archive.extractfile(member) as src,
                (directory / member.name).open("xb") as dst,
            ):
                import shutil

                shutil.copyfileobj(src, dst)
            (directory / member.name).chmod(0o600)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["format_version"] != 1:
        raise ValueError("unsupported manifest version")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["app_commit"]):
        raise ValueError("invalid app commit")
    actual = inspect_database(directory / "tutor.db")
    if any(manifest.get(key) != value for key, value in actual.items()):
        raise ValueError("restored DB does not match manifest")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export"])
    parser.add_argument(
        "--reason", choices=["daily", "shutdown", "pre-upgrade"], required=True
    )
    args = parser.parse_args()
    # 本番 volume を read-only mount した一時コンテナ用。鍵/API キーは不要。
    from app.persistence.config import default_sqlite_path

    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "backup.tar"
        create_archive(
            default_sqlite_path(),
            output,
            app_commit=os.environ.get("APP_COMMIT", ""),
            reason=args.reason,
            app_dirty=os.environ.get("APP_DIRTY") == "true",
        )
        with output.open("rb") as stream:
            import shutil

            shutil.copyfileobj(stream, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

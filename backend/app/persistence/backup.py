"""Tutor DB の整合バックアップと復元（Issue #220）。HTTP には公開しない。

本番 DB は Docker volume の中にあるため、コンテナ内でこの CLI を実行し、
ファイルは標準入出力で受け渡す。ホスト側の手順は scripts/production_backup.sh /
scripts/production_restore.sh と docs/operations/sqlite-backup-runbook.md。

  python -m app.persistence.backup export > tutor.db   # 書込中でも整合コピー
  python -m app.persistence.backup verify < tutor.db   # 受け取ったコピーを検査
  python -m app.persistence.backup restore < tutor.db  # backend 停止中に差し替え

復元は差し替え前の DB を消さず、同じ場所に tutor-before-restore-<時刻>.db として残す。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.engine.url import make_url

from app.persistence.config import get_database_url, is_production
from app.persistence.schema import CURRENT_SCHEMA_VERSION

_SIDECARS = ("-wal", "-shm", "-journal")
# 件数の目安として表示する。中身（本文・回答）は出さない。
_SUMMARY_TABLES = ("source_documents", "learning_items", "learning_events")


def database_path() -> Path:
    """アプリと同じ設定で DB ファイルを解決する。ファイルやディレクトリは作らない。"""
    if is_production():
        from app.persistence.production import check_production_directory

        return check_production_directory()
    url = make_url(get_database_url())
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        raise ValueError("file-based SQLite ではない")
    return Path(url.database)


def verify(path: Path) -> dict[str, int]:
    """整合性と schema version を確かめ、件数の目安を返す。読み取りだけ。"""
    with closing(
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    ) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("integrity_check が ok ではない")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign_key_check で参照切れがある")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "schema_migrations" not in tables:
            raise ValueError("Tutor DB ではない（schema_migrations がない）")
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
            0
        ]
        if not isinstance(version, int) or version < 1:
            raise ValueError("schema version がない")
        if version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"schema version {version} がこのアプリ（{CURRENT_SCHEMA_VERSION}）"
                "より新しい"
            )
        summary = {"schema_version": version}
        for table in _SUMMARY_TABLES:
            if table in tables:
                summary[table] = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
    return summary


def snapshot(source: Path, destination: Path, *, timeout: float = 60) -> dict[str, int]:
    """SQLite backup API で書込中も整合コピーする。失敗時は作りかけを消す。"""
    if not source.is_file() or source.is_symlink():
        raise ValueError("DB ファイルがない")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    deadline = time.monotonic() + timeout

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup がタイムアウトした")

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
            # 元が WAL でも、単独のファイルとして持ち運べる状態にする。
            writer.execute("PRAGMA journal_mode=DELETE")
        summary = verify(destination)
        _fsync(destination)
    except BaseException:
        _remove_with_sidecars(destination)
        raise
    return summary


def export(out: BinaryIO) -> dict[str, int]:
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "tutor.db"
        summary = snapshot(database_path(), copy)
        with copy.open("rb") as stream:
            shutil.copyfileobj(stream, out)
        out.flush()
    return summary


def verify_stream(stream: BinaryIO) -> dict[str, int]:
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "tutor.db"
        _receive(stream, copy)
        return verify(copy)


def restore(stream: BinaryIO, target: Path) -> tuple[dict[str, int], Path | None]:
    """検査済みのコピーで target を差し替える。元の DB は別名で残す。

    書込中の DB を差し替えないよう、backend を止めてから呼ぶ。
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    incoming = target.with_name(f".{target.stem}-restoring-{stamp}{target.suffix}")
    _receive(stream, incoming)
    try:
        with closing(sqlite3.connect(incoming)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
        summary = verify(incoming)
    except BaseException:
        _remove_with_sidecars(incoming)
        raise
    preserved = None
    if target.exists():
        preserved = target.with_name(
            f"{target.stem}-before-restore-{stamp}{target.suffix}"
        )
        # journal / WAL を残すと復元した DB に古い更新が混ざるので一緒に退避する。
        for suffix in ("", *_SIDECARS):
            current = Path(f"{target}{suffix}")
            if current.exists():
                os.rename(current, f"{preserved}{suffix}")
    os.rename(incoming, target)
    _fsync_directory(target.parent)
    return summary, preserved


def _receive(stream: BinaryIO, destination: Path) -> None:
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(stream, out)
        out.flush()
        os.fsync(out.fileno())


def _fsync(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_with_sidecars(path: Path) -> None:
    for suffix in ("", *_SIDECARS):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _describe(summary: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in summary.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tutor DB の整合バックアップと復元")
    parser.add_argument("command", choices=["export", "verify", "restore"])
    args = parser.parse_args(argv)
    # export は標準出力が DB 本体なので、メッセージはすべて標準エラーへ出す。
    try:
        if args.command == "export":
            summary = export(sys.stdout.buffer)
            print(f"整合コピー: {_describe(summary)}", file=sys.stderr)
        elif args.command == "verify":
            summary = verify_stream(sys.stdin.buffer)
            print(f"検査 ok: {_describe(summary)}", file=sys.stderr)
        else:
            summary, preserved = restore(sys.stdin.buffer, database_path())
            print(f"復元: {_describe(summary)}", file=sys.stderr)
            if preserved is not None:
                print(f"差し替え前の DB: {preserved}", file=sys.stderr)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"{args.command} 失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

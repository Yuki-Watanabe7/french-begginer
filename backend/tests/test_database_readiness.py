"""Tutor DB readiness CLI（Issue #219）。"""

import os
import sqlite3

import pytest

from app.persistence import readiness
from app.persistence.db import create_initialized_engine
from app.persistence.readiness import check_database_readiness
from app.persistence.schema import CURRENT_SCHEMA_VERSION


def _sqlite_url(path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def initialized_db(tmp_path):
    path = tmp_path / "tutor.db"
    create_initialized_engine(_sqlite_url(path)).dispose()
    return path


def test_initialized_db_is_ready_and_unchanged(initialized_db):
    before = initialized_db.read_bytes()

    result = check_database_readiness(_sqlite_url(initialized_db))

    assert result.ready, result.detail
    assert result.schema_version == CURRENT_SCHEMA_VERSION
    assert initialized_db.read_bytes() == before
    conn = sqlite3.connect(initialized_db)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
    finally:
        conn.close()
    assert "readiness_probe" not in tables


def test_missing_db_is_not_ready_and_not_created(tmp_path):
    path = tmp_path / "missing" / "tutor.db"

    result = check_database_readiness(_sqlite_url(path))

    assert not result.ready
    assert "未初期化" in result.detail
    assert not path.parent.exists()


def test_uses_tutor_data_dir_like_the_app(initialized_db, monkeypatch):
    monkeypatch.delenv("TUTOR_DATABASE_URL", raising=False)
    monkeypatch.setenv("TUTOR_DATA_DIR", str(initialized_db.parent))

    assert check_database_readiness().ready


@pytest.mark.skipif(os.geteuid() == 0, reason="root は読取専用ファイルにも書ける")
def test_read_only_db_is_not_ready(initialized_db):
    initialized_db.chmod(0o444)
    try:
        result = check_database_readiness(_sqlite_url(initialized_db))
    finally:
        initialized_db.chmod(0o644)

    assert not result.ready
    assert "書き込めない" in result.detail


@pytest.mark.skipif(os.geteuid() == 0, reason="root は権限のないディレクトリも読める")
def test_inaccessible_data_dir_is_not_ready_without_traceback(initialized_db):
    """volume の所有者が実行ユーザーと違う場合。原因を表示して exit 1 にする。"""
    initialized_db.parent.chmod(0o000)
    try:
        result = check_database_readiness(_sqlite_url(initialized_db))
    finally:
        initialized_db.parent.chmod(0o755)

    assert not result.ready
    assert "アクセスできない" in result.detail


def test_schema_version_mismatch_is_not_ready(initialized_db):
    conn = sqlite3.connect(initialized_db)
    with conn:
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (CURRENT_SCHEMA_VERSION + 1, "2026-10-31T00:00:00+00:00"),
        )
    conn.close()

    result = check_database_readiness(_sqlite_url(initialized_db))

    assert not result.ready
    assert result.schema_version == CURRENT_SCHEMA_VERSION + 1


def test_in_memory_db_is_not_a_production_target():
    assert not check_database_readiness("sqlite:///:memory:").ready


def test_cli_exit_code_follows_readiness(initialized_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TUTOR_DATABASE_URL", _sqlite_url(initialized_db))
    assert readiness.main([]) == 0
    assert capsys.readouterr().out.startswith("ready")

    monkeypatch.setenv("TUTOR_DATABASE_URL", _sqlite_url(tmp_path / "none.db"))
    assert readiness.main(["--quiet"]) == 1
    assert capsys.readouterr().err.startswith("not ready")

"""ホスト側のバックアップ・復元スクリプト（Issue #220）を Docker なしで検証する。

production_compose.sh を偽物に差し替え、`run ... python -m ...` は合成 DB に向けた
実際の CLI をそのまま実行する。標準入出力での受け渡しと操作の順序を確かめる。
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app.persistence.backup import snapshot
from app.persistence.db import create_initialized_engine

ROOT = Path(__file__).resolve().parents[2]

FAKE_COMPOSE = """#!/bin/bash
printf 'compose %s\\n' "$*" >> "$TEST_LOG"
[[ "$1" == run ]] || exit 0
while [[ "$1" != python ]]; do shift; done
shift
exec "$TEST_PYTHON" "$@"
"""


def event_count(path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]


def add_event(path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO learning_items (id, item_type, canonical_form, meaning_ja, "
            "status, created_at, metadata_json, source_refs_json) "
            "VALUES ('item', 'vocabulary', 'livre', '本', 'active', "
            "'2026-11-01T00:00:00Z', '{}', '[]')"
        )
        conn.execute(
            "INSERT INTO learning_events (id, learning_item_id, event_type, "
            "exercise_type, result, occurred_at, metadata_json) "
            "VALUES ('event', 'item', 'review', 'fr_to_ja', 'correct', "
            "'2026-11-01T00:00:00Z', '{}')"
        )
        conn.commit()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    scripts = tmp_path / "repo" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("production_backup.sh", "production_restore.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "production_compose.sh").write_text(FAKE_COMPOSE)
    live = tmp_path / "data" / "tutor.db"
    live.parent.mkdir()
    create_initialized_engine(f"sqlite:///{live}").dispose()
    log = tmp_path / "compose.log"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"APP_ENV", "TUTOR_DATA_DIR"}
    }
    env.update(
        TEST_LOG=str(log),
        TEST_PYTHON=sys.executable,
        PYTHONPATH=str(ROOT / "backend"),
        TUTOR_DATABASE_URL=f"sqlite:///{live}",
        FRENCH_BACKUP_DIR=str(tmp_path / "backups"),
    )
    return {"scripts": scripts, "live": live, "log": log, "env": env, "tmp": tmp_path}


def run(repo, script, *args, **env):
    return subprocess.run(
        ["bash", str(repo["scripts"] / script), *args],
        env={**repo["env"], **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def compose_calls(repo) -> list[str]:
    if not repo["log"].exists():
        return []
    return repo["log"].read_text().splitlines()


def test_backup_saves_verified_private_copy(repo):
    add_event(repo["live"])

    result = run(repo, "production_backup.sh")

    assert result.returncode == 0, result.stderr
    backups = repo["tmp"] / "backups"
    files = list(backups.iterdir())
    assert len(files) == 1 and files[0].name.startswith("tutor-")
    assert files[0].suffix == ".db"
    assert event_count(files[0]) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert backups.stat().st_mode & 0o777 == 0o700
    assert "整合コピー" in result.stderr and "検査 ok" in result.stderr
    module = "run --rm --no-deps -T backend python -m app.persistence.backup"
    assert compose_calls(repo) == [
        f"compose {module} export",
        f"compose {module} verify",
    ]


def test_backup_refuses_directory_inside_repository(repo):
    inside = repo["scripts"].parent / "backups"

    result = run(repo, "production_backup.sh", FRENCH_BACKUP_DIR=str(inside))

    assert result.returncode == 1
    assert "リポジトリ内" in result.stderr
    assert compose_calls(repo) == []
    assert not list(inside.iterdir())


def test_failed_backup_leaves_no_file(repo):
    repo["live"].unlink()

    result = run(repo, "production_backup.sh")

    assert result.returncode != 0
    assert "export 失敗" in result.stderr
    assert not list((repo["tmp"] / "backups").iterdir())
    assert not repo["live"].exists()


def test_restore_stops_writers_replaces_db_and_restarts(repo):
    backup = repo["tmp"] / "backup.db"
    snapshot(repo["live"], backup)
    add_event(repo["live"])

    result = run(repo, "production_restore.sh", str(backup))

    assert result.returncode == 0, result.stderr
    assert compose_calls(repo) == [
        "compose stop web backend",
        "compose run --rm --no-deps -T backend python -m app.persistence.backup "
        "restore",
        "compose up -d --wait",
        "compose exec -T backend python -m app.persistence.readiness",
    ]
    assert event_count(repo["live"]) == 0
    (preserved,) = repo["live"].parent.glob("tutor-before-restore-*.db")
    assert event_count(preserved) == 1


def test_bad_backup_keeps_db_and_stays_stopped(repo):
    add_event(repo["live"])
    before = repo["live"].read_bytes()
    bad = repo["tmp"] / "bad.db"
    bad.write_bytes(b"not a database" * 100)

    result = run(repo, "production_restore.sh", str(bad))

    assert result.returncode == 1
    assert "restore 失敗" in result.stderr
    assert compose_calls(repo) == [
        "compose stop web backend",
        "compose run --rm --no-deps -T backend python -m app.persistence.backup "
        "restore",
    ]
    assert repo["live"].read_bytes() == before
    assert sorted(p.name for p in repo["live"].parent.iterdir()) == ["tutor.db"]


def test_restore_requires_existing_file(repo):
    result = run(repo, "production_restore.sh", str(repo["tmp"] / "missing.db"))

    assert result.returncode == 1
    assert compose_calls(repo) == []

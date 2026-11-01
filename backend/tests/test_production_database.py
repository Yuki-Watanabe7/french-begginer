"""本番で DB を黙って新規作成しない。実 UID と journal 権限も検査。"""

import os
import sqlite3

import pytest

from app.persistence import config, production
from app.persistence.config import get_database_url
from app.persistence.db import create_initialized_engine
from app.persistence.readiness import check_database_readiness


@pytest.fixture
def production_dir(tmp_path, monkeypatch):
    directory = tmp_path / "production"
    directory.mkdir(mode=0o700)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TUTOR_DATA_DIR", str(directory))
    monkeypatch.delenv("TUTOR_DATABASE_URL", raising=False)
    monkeypatch.setattr(config, "PRODUCTION_DATA_DIR", directory)
    monkeypatch.setattr(production, "PRODUCTION_UID", os.geteuid())
    monkeypatch.setattr(production, "PRODUCTION_GID", os.getegid())
    return directory


def test_missing_db_does_not_become_empty_database(production_dir):
    with pytest.raises(ValueError, match="本番 DB がありません"):
        create_initialized_engine()
    assert not list(production_dir.iterdir())
    assert not check_database_readiness().ready


def test_only_explicit_initialize_can_create_db(production_dir):
    production.initialize()
    path = production_dir / "tutor.db"
    assert path.stat().st_mode & 0o777 == 0o600
    assert check_database_readiness().ready
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        production.initialize()
    assert path.read_bytes() == before
    engine = create_initialized_engine()
    engine.dispose()
    assert path.read_bytes() == before


def test_database_url_contamination_and_directory_override_fail(
    production_dir, monkeypatch
):
    monkeypatch.setenv("TUTOR_DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(ValueError, match="TUTOR_DATABASE_URL"):
        get_database_url()
    assert not check_database_readiness().ready
    monkeypatch.delenv("TUTOR_DATABASE_URL")
    with pytest.raises(ValueError, match="変更できません"):
        get_database_url("sqlite:///:memory:")
    monkeypatch.setenv("TUTOR_DATA_DIR", str(production_dir / "typo"))
    with pytest.raises(ValueError, match="TUTOR_DATA_DIR"):
        create_initialized_engine()
    assert not list(production_dir.iterdir())


def test_wrong_uid_or_directory_permissions_refuse_startup(production_dir, monkeypatch):
    production_dir.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        production.initialize()
    production_dir.chmod(0o700)
    monkeypatch.setattr(production, "PRODUCTION_UID", os.geteuid() + 1)
    with pytest.raises(ValueError, match="uid/gid"):
        production.initialize()
    assert not list(production_dir.iterdir())


def test_empty_existing_db_is_not_silently_initialized(production_dir):
    path = production_dir / "tutor.db"
    path.touch(mode=0o600)
    with pytest.raises(sqlite3.Error):
        create_initialized_engine()
    assert path.read_bytes() == b""


def test_development_volume_is_rejected_but_named_recovery_is_allowed(
    production_dir, monkeypatch
):
    monkeypatch.setenv("TUTOR_VOLUME_NAME", "french-development")
    with pytest.raises(ValueError, match="volume"):
        get_database_url()
    monkeypatch.setenv(
        "TUTOR_VOLUME_NAME", "french-production-tutor-data-restored-drill"
    )
    assert get_database_url().endswith("/tutor.db")


@pytest.mark.skipif(os.geteuid() == 0, reason="root は directory 権限を迂回する")
def test_directory_without_journal_permission_refuses_startup(production_dir):
    production.initialize()
    path = production_dir / "tutor.db"
    before = path.read_bytes()
    production_dir.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            create_initialized_engine()
        assert not check_database_readiness().ready
    finally:
        production_dir.chmod(0o700)
    assert path.read_bytes() == before

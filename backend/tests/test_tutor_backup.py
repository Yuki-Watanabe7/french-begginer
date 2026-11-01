"""合成 DB だけを使う整合バックアップ・暗号化・復元・旧 schema 訓練。"""

import json
import shutil
import sqlite3
import subprocess
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_tutor_store
from app.domain.tutor import EvidenceSpan, LearningItemCandidate
from app.main import create_app
from app.persistence import backup_store, schema
from app.persistence.backup import (
    create_archive,
    inspect_database,
    sha256,
    snapshot,
    unpack_verified,
)
from app.persistence.backup_store import (
    BackupConfig,
    backup,
    backup_status,
    read_receipt,
    restore,
    retained_ids,
    store_lock,
)
from app.persistence.db import create_db_engine
from app.persistence.recovery_drill import verify_application
from app.repositories.sqlite import TutorSqliteStore
from app.runtime_settings import RuntimeSettings

COMMIT = "a" * 40


@pytest.fixture
def populated_db(tmp_path):
    path = tmp_path / "live.db"
    store = TutorSqliteStore(f"sqlite:///{path}")
    app = create_app(RuntimeSettings())
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as client:
        source = client.post(
            "/api/tutor/sources",
            json={
                "title": "synthetic backup fixture",
                "content": "Un livre et une maison.",
            },
        ).json()
        items = []
        for form, meaning in (
            ("livre", "本"),
            ("maison", "家"),
            ("chat", "猫"),
            ("vin", "ワイン"),
        ):
            response = client.post(
                "/api/tutor/items",
                json={
                    "item_type": "vocabulary",
                    "canonical_form": form,
                    "meaning_ja": meaning,
                    "source_refs": [{"source_document_id": source["id"]}],
                },
            )
            assert response.status_code == 201, response.text
            items.append(response.json()["item"])
        candidate = LearningItemCandidate(
            source_document_id=source["id"],
            item_type="vocabulary",
            canonical_form="livre",
            meaning_ja="本",
            confidence=1,
            evidence_span=EvidenceSpan(start=3, end=8),
            extraction_version="fixture",
        )
        store.learning_item_candidates.create(candidate)
        item_id = items[0]["id"]
        for kind, answer in (("meaning_recognition", "本"), ("ja_to_fr", "livre")):
            result = client.post(
                f"/api/tutor/items/{item_id}/exercises/{kind}/answer",
                json={"answer": answer},
            )
            assert result.status_code == 201, result.text
        assert client.post(f"/api/tutor/items/{item_id}/known").status_code == 200
    store.engine.dispose()
    return path


@pytest.fixture
def encrypted_store(tmp_path, monkeypatch):
    age = shutil.which("age")
    keygen = shutil.which("age-keygen")
    if not age or not keygen:
        pytest.skip("age / age-keygen required (CI installs age)")
    identity = tmp_path / "identity.key"
    subprocess.run([keygen, "-o", str(identity)], capture_output=True, check=True)
    recipients = tmp_path / "recipients.txt"
    result = subprocess.run(
        [keygen, "-y", str(identity)], capture_output=True, check=True
    )
    recipients.write_bytes(result.stdout)
    local = tmp_path / "local"
    remote = tmp_path / "simulated-device"
    remote.mkdir(mode=0o700)
    config = BackupConfig(local, remote, "synthetic-device", recipients, age)
    # 通常は mountpoint・別 filesystem・デバイス ID がすべて必要。
    # この fixture だけ同一ホストの模擬デバイスを注入。実別機器検証とは呼ばない。
    monkeypatch.setattr(
        BackupConfig, "offhost_directory", lambda self, **kwargs: remote
    )
    return config, identity, remote


def provider(path):
    def create(output):
        create_archive(path, output, app_commit=COMMIT, reason="daily")
        return {"image_id": "sha256:synthetic"}

    return create


def test_snapshot_preserves_all_entities_and_directions(populated_db, tmp_path):
    before = inspect_database(populated_db)
    output = tmp_path / "backup.tar"
    manifest = create_archive(populated_db, output, app_commit=COMMIT, reason="daily")
    restored = tmp_path / "restored"
    restored.mkdir()
    assert unpack_verified(output, restored) == manifest
    copied = inspect_database(restored / "tutor.db")
    assert {k: v for k, v in copied.items() if k != "database_sha256"} == {
        k: v for k, v in before.items() if k != "database_sha256"
    }
    assert copied["database_sha256"] == manifest["database_sha256"]
    assert manifest["review_directions"] == {"recognition": 1, "production": 1}
    for name in (
        "source_documents",
        "learning_items",
        "learning_item_candidates",
        "learning_events",
        "learner_states",
        "review_schedules",
        "known_item_overrides",
        "known_item_events",
        "schema_migrations",
    ):
        assert manifest["counts"][name] > 0
    assert sha256(populated_db) == before["database_sha256"]


def test_wal_committed_rows_included_uncommitted_rows_excluded(populated_db, tmp_path):
    with sqlite3.connect(populated_db) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE source_documents SET title='committed'")
        writer.commit()
        writer.execute("UPDATE source_documents SET title='not committed'")
        target = tmp_path / "snapshot.db"
        snapshot(populated_db, target)
        with sqlite3.connect(target) as restored:
            assert (
                restored.execute("SELECT title FROM source_documents").fetchone()[0]
                == "committed"
            )
        writer.rollback()


def test_backup_while_another_connection_commits(populated_db, tmp_path):
    done = threading.Event()
    updates = []

    def write():
        with sqlite3.connect(populated_db) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            for n in range(20):
                writer.execute("UPDATE source_documents SET title=?", (str(n),))
                writer.commit()
                updates.append(n)
            done.set()

    thread = threading.Thread(target=write)
    thread.start()
    try:
        for n in range(3):
            target = tmp_path / f"snapshot{n}.db"
            snapshot(populated_db, target)
            assert inspect_database(target)["counts"]["learning_items"] == 4
    finally:
        thread.join(timeout=10)
    assert done.is_set() and updates


@pytest.mark.parametrize("failure", ["corrupt", "fk", "schema"])
def test_invalid_snapshot_is_never_promoted(populated_db, tmp_path, failure):
    if failure == "corrupt":
        populated_db.write_bytes(b"not a database")
    else:
        with sqlite3.connect(populated_db) as conn:
            if failure == "fk":
                conn.execute("UPDATE learning_events SET learning_item_id='missing'")
            else:
                conn.execute("ALTER TABLE learning_items DROP COLUMN meaning_ja")
    output = tmp_path / "failed.db"
    with pytest.raises((ValueError, sqlite3.Error)):
        snapshot(populated_db, output)
    assert not output.exists()


def test_missing_source_and_existing_destination_are_preserved(populated_db, tmp_path):
    target = tmp_path / "preserved.db"
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        snapshot(populated_db, target)
    assert target.read_bytes() == b"preserve"
    with pytest.raises(ValueError):
        snapshot(tmp_path / "missing.db", tmp_path / "new.db")
    assert not (tmp_path / "missing.db").exists()


def test_locked_database_times_out_without_partial_success(populated_db, tmp_path):
    target = tmp_path / "locked.db"
    with sqlite3.connect(populated_db) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(TimeoutError):
            snapshot(populated_db, target, timeout=0.05)
        writer.rollback()
    assert not target.exists()


def test_encrypt_restore_and_answer_only_on_disposable_copy(
    populated_db, encrypted_store, tmp_path
):
    config, identity, remote = encrypted_store
    original = sha256(populated_db)
    success = backup(config, provider(populated_db), reason="daily")
    assert success["status"] == "encrypted-offhost-copy-verified"
    bundle = remote / success["last_success"]["backup_id"]
    assert (bundle / "archive.age").read_bytes().startswith(b"age-encryption.org/v1")
    assert not list(config.local_dir.rglob("*.db"))
    assert not list(config.local_dir.rglob("*.tar"))
    assert not list(config.local_dir.glob(".pending-*"))
    assert backup_status(config)["rpo_met"]
    restored = tmp_path / "restored"
    record = restore(bundle, restored, identity, age_command=config.age_command)
    assert record["rpo_met"] and not record["rto_met"]
    assert (
        inspect_database(restored / "tutor.db")["counts"]
        == inspect_database(populated_db)["counts"]
    )
    pristine = sha256(restored / "tutor.db")
    verified = verify_application(restored)
    assert verified["application_answer_verified"] and verified["rto_met"]
    assert verified["recovery_seconds"] < 14400
    assert sha256(restored / "tutor.db") == pristine
    assert sha256(populated_db) == original


def test_failure_does_not_replace_success_or_prune(
    populated_db, encrypted_store, monkeypatch
):
    config, _identity, remote = encrypted_store
    success = backup(config, provider(populated_db), reason="daily")
    old = success["last_success"]

    def fail(*args):
        raise OSError("simulated disk full")

    monkeypatch.setattr(backup_store, "copy_encrypted_bundle", fail)
    with pytest.raises(OSError):
        backup(config, provider(populated_db), reason="daily")
    state = json.loads((config.local_dir / "state.json").read_text())
    assert state["status"] == "failed" and state["last_success"] == old
    assert read_receipt(remote / old["backup_id"])["backup_id"] == old["backup_id"]
    assert len(list(remote.iterdir())) == 1


def test_failed_encryption_and_missing_device_leave_no_success(
    populated_db, encrypted_store, monkeypatch
):
    config, _identity, remote = encrypted_store
    config.recipients_file.write_text("invalid-recipient")
    with pytest.raises(ValueError, match="age"):
        backup(config, provider(populated_db), reason="daily")
    assert not list(remote.iterdir())
    assert not backup_status(config)["rpo_met"]

    def unavailable(self, **kwargs):
        raise ValueError("device disconnected")

    monkeypatch.setattr(BackupConfig, "offhost_directory", unavailable)
    with pytest.raises(ValueError, match="disconnected"):
        backup(config, provider(populated_db), reason="daily")
    assert not list(remote.iterdir())


def test_real_mount_guard_does_not_create_missing_mount(tmp_path):
    config = BackupConfig(
        tmp_path / "local",
        tmp_path / "missing-device",
        "test-device",
        tmp_path / "recipients",
    )
    config.local_dir.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="not mounted"):
        config.offhost_directory()
    assert not config.offhost_mount.exists()


def test_wrong_key_corruption_and_existing_restore_target(
    populated_db, encrypted_store, tmp_path
):
    config, identity, remote = encrypted_store
    success = backup(config, provider(populated_db), reason="daily")
    bundle = remote / success["last_success"]["backup_id"]
    wrong = tmp_path / "wrong.key"
    subprocess.run(
        [shutil.which("age-keygen"), "-o", str(wrong)], capture_output=True, check=True
    )
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="age"):
        restore(bundle, target, wrong, age_command=config.age_command)
    assert not target.exists()
    target.mkdir()
    (target / "keep").write_text("keep")
    with pytest.raises(ValueError, match="already exists"):
        restore(bundle, target, identity, age_command=config.age_command)
    assert (target / "keep").read_text() == "keep"
    with (bundle / "archive.age").open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="hash"):
        restore(bundle, tmp_path / "other", identity, age_command=config.age_command)
    assert not (tmp_path / "other").exists()


def test_daily_catchup_and_backup_lock(populated_db, encrypted_store):
    config, _identity, remote = encrypted_store
    success = backup(config, provider(populated_db), reason="daily")

    def must_not_run(path):
        pytest.fail("recent valid backup should be reused")

    assert (
        backup(config, must_not_run, reason="daily", if_due=True)["status"] == "not-due"
    )
    assert len(list(remote.iterdir())) == 1
    with store_lock(config), pytest.raises(ValueError, match="running"):
        backup(config, provider(populated_db), reason="daily")
    assert success["last_success"]


def test_retention_has_daily_weekly_monthly_and_pinned_upgrade():
    now = datetime(2026, 11, 1, tzinfo=UTC)
    receipts = [
        {
            "backup_id": str(n),
            "snapshot_started_at": (now - timedelta(days=n)).isoformat(),
            "reason": "daily",
        }
        for n in range(130)
    ]
    receipts[-1]["reason"] = "pre-upgrade"
    keep = retained_ids(receipts)
    assert {str(n) for n in range(7)} <= keep
    assert {"1", "32", "129"} <= keep
    assert "128" not in keep
    assert len(keep) <= 7 + 4 + 3 + 1


def test_old_schema_upgrade_and_rollback_use_separate_copies(
    populated_db, encrypted_store, tmp_path, monkeypatch
):
    # 実際の v4→v5 差分（known テーブル追加）を持つ DB。
    with sqlite3.connect(populated_db) as conn:
        conn.execute("DROP TABLE known_item_events")
        conn.execute("DROP TABLE known_item_overrides")
        conn.execute("UPDATE schema_migrations SET version=4")
    old_hash = sha256(populated_db)
    config, identity, remote = encrypted_store
    success = backup(config, provider(populated_db), reason="daily")
    bundle = remote / success["last_success"]["backup_id"]
    pristine = tmp_path / "rollback"
    restore(bundle, pristine, identity, age_command=config.age_command)
    pristine_hash = sha256(pristine / "tutor.db")
    assert inspect_database(pristine / "tutor.db")["schema_version"] == 4
    upgrade_path = tmp_path / "upgrade.db"
    snapshot(pristine / "tutor.db", upgrade_path)
    upgraded = TutorSqliteStore(f"sqlite:///{upgrade_path}")
    upgraded.engine.dispose()
    assert inspect_database(upgrade_path)["schema_version"] == 5
    upgraded_hash = sha256(upgrade_path)
    # 旧アプリの schema 初期化を使って旧 DB を開ける。新 DB は拒否し保全する。
    monkeypatch.setattr(schema, "CURRENT_SCHEMA_VERSION", 4)
    monkeypatch.setattr(
        schema, "UPGRADE_STEPS", [s for s in schema.UPGRADE_STEPS if s[0] <= 4]
    )
    engine = create_db_engine(f"sqlite:///{pristine / 'tutor.db'}")
    schema.init_schema(engine)
    engine.dispose()
    new_engine = create_db_engine(f"sqlite:///{upgrade_path}")
    with pytest.raises(schema.SchemaVersionError):
        schema.init_schema(new_engine)
    new_engine.dispose()
    assert sha256(populated_db) == old_hash
    assert sha256(pristine / "tutor.db") == pristine_hash
    assert sha256(upgrade_path) == upgraded_hash


def test_failed_migration_rolls_back_ddl_and_version(populated_db, monkeypatch):
    with sqlite3.connect(populated_db) as conn:
        conn.execute("UPDATE schema_migrations SET version=4")
    before = sha256(populated_db)

    def fail(conn):
        conn.execute(text("CREATE TABLE incomplete_upgrade (id INTEGER)"))
        conn.execute(text("ALTER TABLE source_documents ADD COLUMN incomplete TEXT"))
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(schema, "UPGRADE_STEPS", [(5, fail)])
    engine = create_db_engine(f"sqlite:///{populated_db}")
    with pytest.raises(RuntimeError):
        schema.init_schema(engine)
    engine.dispose()
    assert sha256(populated_db) == before


def test_stale_rpo_and_slow_rto_are_reported_unmet(
    populated_db, encrypted_store, tmp_path
):
    config, identity, remote = encrypted_store
    success = backup(config, provider(populated_db), reason="daily")
    bundle = remote / success["last_success"]["backup_id"]
    record = restore(
        bundle,
        tmp_path / "stale",
        identity,
        age_command=config.age_command,
        recovery_point=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        recovery_started_at=(datetime.now(UTC) - timedelta(hours=5)).isoformat(),
    )
    assert not record["rpo_met"] and not record["rto_met"]
    verified = verify_application(tmp_path / "stale")
    assert verified["application_answer_verified"] and not verified["rto_met"]


def test_archive_path_traversal_is_rejected(tmp_path):
    import io
    import tarfile

    archive_path = tmp_path / "evil.tar"
    with tarfile.open(archive_path, "w") as archive:
        entry = tarfile.TarInfo("../escape")
        entry.size = 3
        archive.addfile(entry, io.BytesIO(b"bad"))
    destination = tmp_path / "target"
    destination.mkdir()
    with pytest.raises(ValueError, match="members"):
        unpack_verified(archive_path, destination)
    assert not (tmp_path / "escape").exists()

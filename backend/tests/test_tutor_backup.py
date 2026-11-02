"""合成 DB だけを使う整合バックアップと復元（Issue #220）。"""

import io
import sqlite3
import threading
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.domain.tutor import EvidenceSpan, LearningItemCandidate
from app.main import create_app
from app.persistence.backup import export, restore, snapshot, verify, verify_stream
from app.persistence.schema import CURRENT_SCHEMA_VERSION
from app.repositories.sqlite import TutorSqliteStore
from app.runtime_settings import RuntimeSettings

LEARNING_TABLES = (
    "source_documents",
    "learning_items",
    "learning_item_candidates",
    "learning_events",
    "learner_states",
    "review_schedules",
    "known_item_overrides",
    "known_item_events",
    "schema_migrations",
)


def counts(path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as conn:
        return {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in LEARNING_TABLES
        }


def answer(path, answer_text="本") -> None:
    """実際の回答 API で LearningEvent を1件足す。"""
    store = TutorSqliteStore(f"sqlite:///{path}")
    app = create_app(RuntimeSettings())
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as client:
        item_id = client.get("/api/tutor/items").json()[0]["id"]
        response = client.post(
            f"/api/tutor/items/{item_id}/exercises/meaning_recognition/answer",
            json={"answer": answer_text},
        )
        assert response.status_code == 201, response.text
    store.engine.dispose()


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
        for form, meaning in (("livre", "本"), ("maison", "家")):
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
        store.learning_item_candidates.create(
            LearningItemCandidate(
                source_document_id=source["id"],
                item_type="vocabulary",
                canonical_form="livre",
                meaning_ja="本",
                confidence=1,
                evidence_span=EvidenceSpan(start=3, end=8),
                extraction_version="fixture",
            )
        )
        item_id = items[0]["id"]
        for kind, text in (("meaning_recognition", "本"), ("ja_to_fr", "livre")):
            result = client.post(
                f"/api/tutor/items/{item_id}/exercises/{kind}/answer",
                json={"answer": text},
            )
            assert result.status_code == 201, result.text
        assert client.post(f"/api/tutor/items/{item_id}/known").status_code == 200
    store.engine.dispose()
    return path


@pytest.fixture
def backup_bytes(populated_db, tmp_path):
    copy = tmp_path / "backup.db"
    snapshot(populated_db, copy)
    return copy.read_bytes()


def test_snapshot_keeps_all_learning_data(populated_db, tmp_path):
    before = populated_db.read_bytes()
    target = tmp_path / "snapshot.db"

    summary = snapshot(populated_db, target)

    assert counts(target) == counts(populated_db)
    assert all(value > 0 for value in counts(target).values())
    assert summary["schema_version"] == CURRENT_SCHEMA_VERSION
    assert summary["learning_events"] == 2
    assert target.stat().st_mode & 0o777 == 0o600
    assert populated_db.read_bytes() == before


def test_wal_committed_rows_included_uncommitted_rows_excluded(populated_db, tmp_path):
    with closing(sqlite3.connect(populated_db)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE source_documents SET title='committed'")
        writer.commit()
        writer.execute("UPDATE source_documents SET title='not committed'")
        target = tmp_path / "snapshot.db"
        snapshot(populated_db, target)
        writer.rollback()
    with closing(sqlite3.connect(target)) as restored:
        assert restored.execute("SELECT title FROM source_documents").fetchone() == (
            "committed",
        )
        assert restored.execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_backup_while_another_connection_commits(populated_db, tmp_path):
    done = threading.Event()

    def write():
        with closing(sqlite3.connect(populated_db)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            for n in range(20):
                writer.execute("UPDATE source_documents SET title=?", (str(n),))
                writer.commit()
        done.set()

    thread = threading.Thread(target=write)
    thread.start()
    try:
        for n in range(3):
            target = tmp_path / f"snapshot{n}.db"
            assert snapshot(populated_db, target)["learning_items"] == 2
    finally:
        thread.join(timeout=10)
    assert done.is_set()


@pytest.mark.parametrize("failure", ["corrupt", "fk", "newer_schema", "not_tutor"])
def test_invalid_snapshot_is_never_kept(populated_db, tmp_path, failure):
    if failure == "corrupt":
        populated_db.write_bytes(b"not a database")
    else:
        with closing(sqlite3.connect(populated_db)) as conn:
            if failure == "fk":
                conn.execute("UPDATE learning_events SET learning_item_id='missing'")
            elif failure == "newer_schema":
                conn.execute(
                    "UPDATE schema_migrations SET version=?",
                    (CURRENT_SCHEMA_VERSION + 1,),
                )
            else:
                conn.execute("DROP TABLE schema_migrations")
            conn.commit()
    target = tmp_path / "failed.db"
    with pytest.raises((ValueError, sqlite3.Error)):
        snapshot(populated_db, target)
    assert not target.exists()


def test_missing_source_and_existing_destination_are_preserved(populated_db, tmp_path):
    target = tmp_path / "preserved.db"
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        snapshot(populated_db, target)
    assert target.read_bytes() == b"preserve"
    with pytest.raises(ValueError):
        snapshot(tmp_path / "missing.db", tmp_path / "new.db")
    assert not (tmp_path / "missing.db").exists()
    assert not (tmp_path / "new.db").exists()


def test_locked_database_times_out_without_partial_file(populated_db, tmp_path):
    target = tmp_path / "locked.db"
    with closing(sqlite3.connect(populated_db)) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(TimeoutError):
            snapshot(populated_db, target, timeout=0.05)
        writer.rollback()
    assert not target.exists()


def test_export_streams_configured_db_and_verify_accepts_it(populated_db, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("TUTOR_DATABASE_URL", f"sqlite:///{populated_db}")
    out = io.BytesIO()

    exported = export(out)

    assert exported == verify_stream(io.BytesIO(out.getvalue()))
    assert exported["learning_items"] == 2
    with pytest.raises(sqlite3.Error):
        verify_stream(io.BytesIO(out.getvalue()[:4096]))


def test_restore_replaces_db_and_keeps_previous_one(
    populated_db, backup_bytes, tmp_path
):
    answer(populated_db)
    after_backup = counts(populated_db)
    # 退避しないと復元後の DB に古い WAL が混ざる。
    (tmp_path / "live.db-wal").write_bytes(b"")

    summary, preserved = restore(io.BytesIO(backup_bytes), populated_db)

    assert summary["learning_events"] == 2
    assert counts(populated_db)["learning_events"] == 2
    assert preserved is not None and preserved.parent == tmp_path
    assert preserved.name.startswith("live-before-restore-")
    assert counts(preserved) == after_backup
    assert after_backup["learning_events"] == 3
    assert not (tmp_path / "live.db-wal").exists()
    assert (tmp_path / f"{preserved.name}-wal").exists()
    assert not list(tmp_path.glob(".live-restoring-*"))
    assert populated_db.stat().st_mode & 0o777 == 0o600
    answer(populated_db)  # 復元した DB で学習を続けられる
    assert counts(populated_db)["learning_events"] == 3


@pytest.mark.parametrize("payload", ["garbage", "truncated", "newer_schema"])
def test_restore_rejects_bad_backup_without_touching_db(
    populated_db, backup_bytes, tmp_path, payload
):
    if payload == "garbage":
        data = b"not a database" * 100
    elif payload == "truncated":
        data = backup_bytes[:4096]
    else:
        newer = tmp_path / "newer.db"
        newer.write_bytes(backup_bytes)
        with closing(sqlite3.connect(newer)) as conn:
            conn.execute(
                "UPDATE schema_migrations SET version=?", (CURRENT_SCHEMA_VERSION + 1,)
            )
            conn.commit()
        data = newer.read_bytes()
    before = populated_db.read_bytes()

    with pytest.raises((ValueError, sqlite3.Error)):
        restore(io.BytesIO(data), populated_db)

    assert populated_db.read_bytes() == before
    assert not list(tmp_path.glob(".live-restoring-*"))
    assert not list(tmp_path.glob("live-before-restore-*"))


def test_old_backup_restored_to_new_location_is_upgraded_on_start(
    backup_bytes, tmp_path
):
    """v4 時代のバックアップも、復元後の起動時 upgrade で現行版として使える。"""
    old = tmp_path / "v4.db"
    old.write_bytes(backup_bytes)
    with closing(sqlite3.connect(old)) as conn:
        conn.execute("DROP TABLE known_item_events")
        conn.execute("DROP TABLE known_item_overrides")
        conn.execute("UPDATE schema_migrations SET version=4")
        conn.commit()
    target = tmp_path / "fresh" / "tutor.db"
    target.parent.mkdir()

    summary, preserved = restore(io.BytesIO(old.read_bytes()), target)

    assert summary["schema_version"] == 4 and preserved is None
    answer(target)
    assert verify(target)["schema_version"] == CURRENT_SCHEMA_VERSION
    assert counts(target)["learning_events"] == 3

"""合成 DB だけを使う公開 Snapshot の書き出し（Issue #221）。"""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from export_public_snapshot import main
from pydantic import ValidationError

from app.domain.public_snapshot import (
    MAX_PUBLIC_CARDS,
    PublicCard,
    PublicSnapshot,
    PublicSnapshotAllowlist,
    PublicSnapshotError,
    build_public_snapshot,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearningEvent,
    LearningItem,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    apply_review_event,
)
from app.persistence.schema import CURRENT_SCHEMA_VERSION
from app.repositories.sqlite import TutorSqliteStore
from app.services.public_snapshot_export import export_public_snapshot

NOW = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
SYNTHETIC_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "public-snapshot.synthetic.json"
)
SECRET = "sk-synthetic-0123456789abcdefghijklmnopqrstuv"
PRIVATE_SOURCE_TITLE = "合成: Yuki との個人的な会話メモ"
PRIVATE_SOURCE_TEXT = (
    "Bonjour ! Je m'appelle Yuki. Écris-moi à yuki.private@example.com. "
    "S'il vous plaît, nous parlons demain."
)
CARD_KEYS = {
    "card_id",
    "item_type",
    "canonical_form",
    "meaning_ja",
    "explanation_ja",
    "level",
}


def synthetic_db(path: Path) -> dict[str, object]:
    """個人情報・秘密・履歴を含む合成 DB。公開してよいのは public の3件だけ。"""
    store = TutorSqliteStore(f"sqlite:///{path}")
    source = store.source_documents.create(
        SourceDocument(
            title=PRIVATE_SOURCE_TITLE,
            content=PRIVATE_SOURCE_TEXT,
            metadata={"api_key": SECRET, "device_path": "/Users/yuki/private.txt"},
        )
    )
    ref = SourceRef(
        source_document_id=source.id,
        evidence_span=EvidenceSpan(start=0, end=7, text="Bonjour"),
        confidence=0.9,
    )
    public = [
        LearningItem(
            item_type="vocabulary",
            canonical_form="bonjour",
            meaning_ja="こんにちは",
            explanation_ja="日中の一般的なあいさつ。",
            level="A1",
            source_refs=[ref],
            metadata={"private_note": "Yuki が会話で使った", "token": SECRET},
        ),
        LearningItem(
            item_type="expression",
            canonical_form="s'il vous plaît",
            meaning_ja="お願いします",
            level="A1",
            status="mastered",
        ),
        LearningItem(
            item_type="conjugation",
            canonical_form="nous parlons",
            meaning_ja="私たちは話す",
            explanation_ja="parler の直説法現在、nous の形。\n語尾は -ons。",
        ),
    ]
    private = LearningItem(
        item_type="expression",
        canonical_form="je m'appelle Yuki",
        meaning_ja="私の名前は Yuki です",
        source_refs=[ref],
    )
    suspended = LearningItem(
        item_type="vocabulary",
        canonical_form="demain",
        meaning_ja="明日",
        status="suspended",
    )
    for item in [*public, private, suspended]:
        store.learning_items.create(item)

    event = LearningEvent(
        learning_item_id=public[0].id,
        exercise_type="meaning_recognition",
        result="incorrect",
        occurred_at=NOW - timedelta(days=1),
        response_time_ms=4321,
        metadata={"answer": "さようなら"},
    )
    schedule = ReviewSchedule(
        learning_item_id=public[0].id,
        skill_direction="recognition",
        due_at=datetime(2026, 11, 4, 7, 15, tzinfo=UTC),
        interval_days=1.0,
        review_count=1,
        lapse_count=1,
    )
    store.learning_progress.append_event_upsert_state_and_schedule(
        event, apply_review_event(None, event), schedule
    )
    store.engine.dispose()
    return {
        "source": source,
        "public": public,
        "private": private,
        "suspended": suspended,
        "event": event,
    }


def write_allowlist(path: Path, items: list[LearningItem]) -> Path:
    path.write_text(
        json.dumps(
            {
                "items": [
                    {"item_id": item.id, "canonical_form": item.canonical_form}
                    for item in items
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys |= collect_keys(child)
        return keys
    if isinstance(value, list):
        return set().union(*(collect_keys(child) for child in value))
    return set()


@pytest.fixture
def fixture(tmp_path):
    db = tmp_path / "tutor-backup.db"
    data = synthetic_db(db)
    allowlist = write_allowlist(tmp_path / "allowlist.json", data["public"])
    return {"db": db, "allowlist": allowlist, "tmp": tmp_path, **data}


def export(fixture, name="out", **kwargs):
    return export_public_snapshot(
        database=fixture["db"],
        allowlist=fixture["allowlist"],
        out=fixture["tmp"] / "snapshots" / name,
        now=NOW,
        **kwargs,
    )


def test_synthetic_fixture_exports_viewable_minimal_snapshot(fixture):
    result = export(fixture)

    assert result.path == fixture["tmp"] / "snapshots" / "out" / "snapshot.json"
    assert [p.name for p in result.path.parent.iterdir()] == ["snapshot.json"]
    assert result.card_count == 3
    assert result.sha256 == file_sha256(result.path)
    # docs の合成例は #222 の開発用。同じ入力から同じ内容になる。
    assert result.path.read_bytes() == SYNTHETIC_EXAMPLE.read_bytes()

    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "generated_at", "cards"}
    assert payload["schema_version"] == "public-v1"
    assert payload["generated_at"] == "2026-11-03T09:30:00Z"
    assert [card["card_id"] for card in payload["cards"]] == [
        "card-001",
        "card-002",
        "card-003",
    ]
    assert [card["canonical_form"] for card in payload["cards"]] == [
        "bonjour",
        "s'il vous plaît",
        "nous parlons",
    ]
    for card in payload["cards"]:
        assert set(card) <= CARD_KEYS
        assert {"card_id", "item_type", "canonical_form", "meaning_ja"} <= set(card)
    # 任意項目は null にせず省く。
    assert set(payload["cards"][1]) == {
        "card_id",
        "item_type",
        "canonical_form",
        "meaning_ja",
        "level",
    }


def test_snapshot_excludes_history_private_source_secrets_and_unknown_keys(fixture):
    result = export(fixture)
    text = result.path.read_text(encoding="utf-8")

    assert collect_keys(json.loads(text)) == {
        "schema_version",
        "generated_at",
        "cards",
        *CARD_KEYS,
    }
    item_ids = [item.id for item in [*fixture["public"], fixture["private"]]]
    forbidden = [
        *item_ids,
        fixture["source"].id,
        fixture["event"].id,
        SECRET,
        "sk-",
        PRIVATE_SOURCE_TITLE,
        "Yuki",
        "example.com",
        "/Users/",
        "Écris-moi",
        "demain",
        "さようなら",
        "4321",
        "2026-11-04",
        "2026-11-02",
    ]
    for value in forbidden:
        assert value not in text, value


def test_export_reads_database_without_modifying_it(fixture):
    db = fixture["db"]
    # 古い schema のコピーでも upgrade しない。通常の Store なら version を書き込む。
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "UPDATE schema_migrations SET version = ?", (CURRENT_SCHEMA_VERSION - 1,)
        )
        conn.commit()
    before = file_sha256(db)
    db.chmod(0o444)
    try:
        assert export(fixture).card_count == 3
    finally:
        db.chmod(0o644)

    assert file_sha256(db) == before
    leftovers = [p.name for p in db.parent.iterdir() if p.name.startswith(db.name)]
    assert leftovers == [db.name]


def test_snapshot_file_parses_back_and_rejects_unknown_or_private_keys(fixture):
    payload = json.loads(export(fixture).path.read_text(encoding="utf-8"))
    assert PublicSnapshot.model_validate(payload).cards[0].canonical_form == "bonjour"

    with_due = json.loads(json.dumps(payload))
    with_due["cards"][0]["review_hint"] = [
        {"due_at": "2026-11-04T07:15:00Z", "skill_direction": "recognition"}
    ]
    with_root_key = {**payload, "learning_events": []}
    private_version = {**payload, "schema_version": "private-v1"}
    db_id = json.loads(json.dumps(payload))
    db_id["cards"][0]["card_id"] = fixture["public"][0].id
    for broken in (with_due, with_root_key, private_version, db_id):
        with pytest.raises(ValidationError):
            PublicSnapshot.model_validate(broken)


@pytest.mark.parametrize(
    "text",
    [
        "詳しくは https://example.org/lesson を参照",
        "www.example.org",
        "連絡先 someone@example.com",
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "タブ\tを含む",
        "復帰\rを含む",
        SECRET,
        "id=3f2b6c1e-8a4d-4f0b-9c3e-2a1d5e7f9b10",
        "a" * 501,
    ],
)
def test_card_text_rejects_urls_html_controls_secrets_and_overlong(text):
    with pytest.raises(ValidationError):
        PublicCard(
            card_id="card-001",
            item_type="vocabulary",
            canonical_form="bonjour",
            meaning_ja=text,
        )


@pytest.mark.parametrize(
    "text",
    [
        "je/tu/il/elle/nous/vous/ils/elles で語尾が変わる",
        "c'est-à-dire",
        "1行目\n2行目",
        "être と avoir の使い分け（A < B ではない）",
        "« Bonjour ! »",
    ],
)
def test_card_text_accepts_ordinary_learning_text(text):
    card = PublicCard(
        card_id="card-001",
        item_type="grammar",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        explanation_ja=text,
    )
    assert card.explanation_ja == text


def item(**overrides) -> LearningItem:
    values = {
        "item_type": "vocabulary",
        "canonical_form": "bonjour",
        "meaning_ja": "こんにちは",
    }
    return LearningItem(**{**values, **overrides})


def allowlist_for(*items: LearningItem) -> PublicSnapshotAllowlist:
    return PublicSnapshotAllowlist.model_validate(
        {
            "items": [
                {"item_id": entry.id, "canonical_form": entry.canonical_form}
                for entry in items
            ]
        }
    )


def test_build_rejects_missing_or_mismatched_item_without_echoing_text():
    missing = item()
    with pytest.raises(PublicSnapshotError, match="1 件目.*DB にない"):
        build_public_snapshot(allowlist_for(missing), [], generated_at=NOW)

    stored = item(canonical_form="merci")
    allowlist = PublicSnapshotAllowlist.model_validate(
        {"items": [{"item_id": stored.id, "canonical_form": "bonjour"}]}
    )
    with pytest.raises(PublicSnapshotError, match="canonical_form が DB と一致しない"):
        build_public_snapshot(allowlist, [stored], generated_at=NOW)

    leaky = item(explanation_ja=f"キーは {SECRET}")
    with pytest.raises(PublicSnapshotError) as excinfo:
        build_public_snapshot(allowlist_for(leaky), [leaky], generated_at=NOW)
    assert "explanation_ja" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)

    too_long = item(canonical_form="a" * 201)
    with pytest.raises(PublicSnapshotError, match="canonical_form"):
        build_public_snapshot(allowlist_for(too_long), [too_long], generated_at=NOW)


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": [{"item_id": "a", "canonical_form": "x", "explanation_ja": "y"}]},
        {"items": [{"item_id": "a", "canonical_form": "x"}], "include": "all"},
        {
            "items": [
                {"item_id": "a", "canonical_form": "x"},
                {"item_id": "a", "canonical_form": "x"},
            ]
        },
        {
            "items": [
                {"item_id": str(i), "canonical_form": "x"}
                for i in range(MAX_PUBLIC_CARDS + 1)
            ]
        },
    ],
)
def test_allowlist_rejects_empty_unknown_duplicate_and_over_limit(payload):
    with pytest.raises(ValidationError):
        PublicSnapshotAllowlist.model_validate(payload)


def test_export_refuses_output_inside_git_tree_or_existing_dir(fixture):
    repo = fixture["tmp"] / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(PublicSnapshotError, match="Git 作業ツリー"):
        export_public_snapshot(
            database=fixture["db"],
            allowlist=fixture["allowlist"],
            out=repo / "frontend" / "public" / "snapshot",
            now=NOW,
        )
    assert not (repo / "frontend").exists()

    existing = fixture["tmp"] / "snapshots" / "out"
    existing.mkdir(parents=True)
    (existing / "tutor.db").write_bytes(b"stale")
    with pytest.raises(PublicSnapshotError, match="既にある"):
        export(fixture)
    assert [p.name for p in existing.iterdir()] == ["tutor.db"]


def test_failed_export_creates_nothing(fixture):
    leaky = item(explanation_ja="参考: https://example.org/private?token=abc")
    store = TutorSqliteStore(f"sqlite:///{fixture['db']}")
    store.learning_items.create(leaky)
    store.engine.dispose()
    write_allowlist(fixture["allowlist"], [*fixture["public"], leaky])

    with pytest.raises(PublicSnapshotError, match="4 件目.*URL を含む"):
        export(fixture)
    assert not (fixture["tmp"] / "snapshots").exists()


def test_export_refuses_missing_or_non_tutor_database(fixture, tmp_path):
    with pytest.raises(PublicSnapshotError, match="DB ファイルがない"):
        export_public_snapshot(
            database=tmp_path / "missing.db",
            allowlist=fixture["allowlist"],
            out=tmp_path / "snapshots" / "missing",
            now=NOW,
        )

    other = tmp_path / "other.db"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE notes (body TEXT)")
    with pytest.raises(ValueError, match="Tutor DB ではない"):
        export_public_snapshot(
            database=other,
            allowlist=fixture["allowlist"],
            out=tmp_path / "snapshots" / "other",
            now=NOW,
        )
    assert not (tmp_path / "snapshots").exists()


def test_cli_draft_lists_non_suspended_items_and_feeds_export(fixture, capsys):
    assert main(["draft", "--database", str(fixture["db"])]) == 0
    captured = capsys.readouterr()
    draft = json.loads(captured.out)
    assert "一般公開してよい Item だけを残して" in captured.err
    assert [entry["canonical_form"] for entry in draft["items"]] == [
        "bonjour",
        "s'il vous plaît",
        "nous parlons",
        "je m'appelle Yuki",
    ]
    assert set(collect_keys(draft)) == {"items", "item_id", "canonical_form"}

    # 本人が公開しない Item を消した想定。
    draft["items"] = draft["items"][:3]
    fixture["allowlist"].write_text(json.dumps(draft), encoding="utf-8")
    out = fixture["tmp"] / "snapshots" / "cli"
    args = ["export", "--database", str(fixture["db"])]
    args += ["--allowlist", str(fixture["allowlist"]), "--out", str(out)]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert "（3 枚）" in captured.out
    assert "外部へは送信していません" in captured.out
    payload = json.loads((out / "snapshot.json").read_text(encoding="utf-8"))
    assert len(payload["cards"]) == 3


def test_cli_reports_failure_without_echoing_secret(fixture, capsys):
    entry = {"item_id": SECRET, "canonical_form": "x", "note": SECRET}
    fixture["allowlist"].write_text(json.dumps({"items": [entry]}), encoding="utf-8")
    out = fixture["tmp"] / "snapshots" / "cli"
    args = ["export", "--database", str(fixture["db"])]
    args += ["--allowlist", str(fixture["allowlist"]), "--out", str(out)]
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "export 失敗: allowlist が不正" in captured.err
    assert SECRET not in captured.err + captured.out
    assert not out.exists()

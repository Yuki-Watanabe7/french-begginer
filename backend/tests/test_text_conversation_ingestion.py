"""テキスト / Markdown と会話 JSON を SourceDocument にする（Issue #194）。

ネットワークは使わない。未知の JSON は会話として解釈しない。
"""

from __future__ import annotations

import ast
import inspect
import json
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_conversation_ingestion_service,
    get_learning_item_extractor,
    get_text_file_ingestion_service,
    get_tutor_store,
)
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    MAX_SOURCE_TEXT_CHARS,
    IngestAction,
    SourceIngestionError,
    content_digest,
    normalize_source_text,
    segment_for_span,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.conversation_log import CONVERSATION_ADAPTER_VERSION
from app.ingestion.text_file import TEXT_FILE_ADAPTER_VERSION, markdown_to_plain
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.conversation_ingestion import ConversationIngestionService
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.text_file_ingestion import TextFileIngestionService

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
SECRET = "acct-DO-NOT-STORE"
SECRET_URL = "https://example.com/users/acct-DO-NOT-STORE"

MARKDOWN = """\
# Le café

- **Bonjour**, [élève](https://example.com/users/acct-DO-NOT-STORE)
- 今日は *café* を飲む

> Il prend un café.

[id]: https://example.com/users/acct-DO-NOT-STORE

```fr
l'élève
```

<https://example.com/users/acct-DO-NOT-STORE>
"""
MARKDOWN_CONTENT = (
    "Le café\n\nBonjour, élève\n今日は café を飲む\n\nIl prend un café.\n\nl'élève"
)

PLAIN = "Aujourd'hui, l'élève apprend.\r\n\r\nIl prend un café.\n"
PLAIN_CONTENT = "Aujourd'hui, l'élève apprend.\n\nIl prend un café."

CONVERSATION = {
    "title": "会話練習",
    "messages": [
        {
            "speaker": "user",
            "text": "Bonjour.",
            "timestamp": "2026-04-01T12:00:00+09:00",
        },
        {
            "speaker": "partner",
            "text": "こんにちは。Il prend un café.",
            "timestamp": "2026-04-01T03:00:01Z",
        },
        {"speaker": "user", "text": "   ", "timestamp": "2026-04-01T03:00:02Z"},
        {"speaker": "partner", "text": "How are you?"},
        {"speaker": "user", "text": "**Bonjour**"},
    ],
}
CONVERSATION_CONTENT = (
    "Bonjour.\n\nこんにちは。Il prend un café.\n\nHow are you?\n\n**Bonjour**"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"network call: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_markdown_to_plain_drops_links_and_keeps_french_text() -> None:
    plain = markdown_to_plain(MARKDOWN)
    assert SECRET not in plain
    assert SECRET_URL not in plain
    assert normalize_source_text(plain) == MARKDOWN_CONTENT
    assert markdown_to_plain(plain) == plain


def test_txt_and_markdown_import_keep_provenance_and_plain_text(
    store: TutorSqliteStore,
) -> None:
    text = _text_service(store).ingest_text_file(
        source=BytesIO(PLAIN.encode()),
        filename="../../leçon.txt",
        declared_media_type="text/plain; charset=utf-8",
        title="Cours",
        note="depuis le fichier",
    )
    assert text.action is IngestAction.create
    document = text.document
    assert document.source_type == "conversation_log"
    assert document.title == "Cours"
    assert document.content == PLAIN_CONTENT
    assert document.content_hash == content_digest(PLAIN_CONTENT)
    assert "# " not in document.content
    assert document.provenance is not None
    assert document.provenance.filename == "leçon.txt"
    assert document.provenance.canonical_locator == document.metadata["file_sha256"]
    assert document.provenance.adapter_version == TEXT_FILE_ADAPTER_VERSION
    assert document.provenance.ingestion_version == INGESTION_VERSION
    assert document.provenance.ingested_at == FIXED
    assert document.provenance.mime_type == "text/plain"
    assert document.metadata["source_format"] == "plain_text"
    assert document.metadata["note"] == "depuis le fichier"
    assert document.segments[0].speaker is None
    assert document.segments[0].timestamp is None
    assert "../" not in document.model_dump_json()

    log_file = _text_service(store).ingest_text_file(
        source=BytesIO(b"# Bonjour\n"),
        filename="memo.log",
        declared_media_type=None,
    )
    assert log_file.document.content == "# Bonjour"
    assert log_file.document.metadata["source_format"] == "plain_text"

    markdown = _text_service(store).ingest_text_file(
        source=BytesIO(MARKDOWN.encode()),
        filename="leçon.md",
        declared_media_type="text/markdown",
    )
    assert markdown.document.content == MARKDOWN_CONTENT
    assert markdown.document.metadata["source_format"] == "markdown"
    assert markdown.document.provenance is not None
    assert markdown.document.provenance.mime_type == "text/markdown"
    assert SECRET not in markdown.document.model_dump_json()
    cafe = _span(markdown.document, "café")
    assert cafe.speaker is None
    assert markdown.document.content[cafe.normalized_start : cafe.normalized_end] == (
        MARKDOWN_CONTENT
    )


def test_plain_text_does_not_strip_markdown_syntax(store: TutorSqliteStore) -> None:
    raw = "# cafe\u0301\r\n\r\n**Bonjour**\n"
    document = (
        _text_service(store)
        .ingest_text_file(
            source=BytesIO(raw.encode()),
            filename="notes.txt",
            declared_media_type="text/plain",
        )
        .document
    )
    assert document.content == "# café\n\n**Bonjour**"
    assert document.content_hash == content_digest(document.content)
    assert document.provenance is not None
    assert document.provenance.original_content_hash == content_digest(raw)


def test_markdown_normalization_is_deterministic(store: TutorSqliteStore) -> None:
    raw = "# cafe\u0301\r\n\r\n\r\n**Bonjour**\r\n"
    first = _text_service(store).ingest_text_file(
        source=BytesIO(raw.encode()),
        filename="leçon.md",
        declared_media_type="text/x-markdown",
    )
    second = _text_service(store).ingest_text_file(
        source=BytesIO(raw.encode()),
        filename="autre.markdown",
        declared_media_type="application/octet-stream",
        title="Ignoré",
    )
    assert first.document.content == "café\n\nBonjour"
    assert second.action is IngestAction.reuse
    assert second.document.id == first.document.id
    assert second.document.title == "leçon"
    assert first.document.content_hash == content_digest(first.document.content)
    assert first.document.provenance is not None
    assert (
        first.document.provenance.original_content_hash != first.document.content_hash
    )
    other = _text_service(store).ingest_text_file(
        source=BytesIO(b"Autre phrase.\n"),
        filename="autre.md",
        declared_media_type=None,
    )
    assert other.action is IngestAction.create
    assert other.document.id != first.document.id


def test_conversation_json_keeps_speaker_time_and_message_order(
    store: TutorSqliteStore,
) -> None:
    payload = json.dumps(CONVERSATION, ensure_ascii=False).encode()
    saved = _conversation_service(store).ingest_conversation(
        source=BytesIO(payload),
        filename="../../dialogue.json",
        declared_media_type="application/json; charset=utf-8",
        note="cours oral",
    )
    document = saved.document
    assert document.source_type == "conversation_log"
    assert document.title == "会話練習"
    assert document.content == CONVERSATION_CONTENT
    assert document.language == "fr"
    assert [segment.speaker for segment in document.segments] == [
        "user",
        "partner",
        "partner",
        "user",
    ]
    assert [segment.timestamp for segment in document.segments] == [
        "2026-04-01T03:00:00Z",
        "2026-04-01T03:00:01Z",
        None,
        None,
    ]
    assert all(segment.start_seconds is None for segment in document.segments)
    assert document.metadata["source_format"] == "conversation_json"
    assert document.metadata["message_count"] == 4
    assert document.metadata["empty_message_count"] == 1
    assert document.metadata["note"] == "cours oral"
    assert "messages" not in document.metadata
    assert document.provenance is not None
    assert document.provenance.filename == "dialogue.json"
    assert document.provenance.adapter_version == CONVERSATION_ADAPTER_VERSION
    assert document.provenance.ingested_at == FIXED
    assert document.provenance.mime_type == "application/json"
    assert "../" not in document.model_dump_json()
    _assert_slices(
        document,
        ["Bonjour.", "こんにちは。Il prend un café.", "How are you?", "**Bonjour**"],
    )
    cafe = _span(document, "café")
    assert cafe.speaker == "partner"
    assert cafe.timestamp == "2026-04-01T03:00:01Z"
    gap = document.segments[0].normalized_end
    with pytest.raises(SourceIngestionError):
        segment_for_span(document.segments, start=gap, end=gap + 2)

    reversed_time = {
        "messages": [
            {"speaker": "b", "text": "deuxième", "timestamp": "2026-04-01T00:00:02Z"},
            {"speaker": "a", "text": "premier", "timestamp": "2026-04-01T00:00:01Z"},
        ]
    }
    ordered = _conversation_service(store).ingest_conversation(
        source=BytesIO(json.dumps(reversed_time).encode()),
        filename="order.json",
        declared_media_type="application/json",
    )
    assert ordered.document.content == "deuxième\n\npremier"
    assert ordered.document.title == "order"


def test_conversation_without_filename_uses_json_title(store: TutorSqliteStore) -> None:
    payload = json.dumps(
        {"title": "  Oral  ", "messages": [{"text": "Salut"}]}
    ).encode()
    document = (
        _conversation_service(store)
        .ingest_conversation(
            source=BytesIO(payload),
            filename=None,
            declared_media_type="application/json",
        )
        .document
    )
    assert document.title == "Oral"
    assert document.provenance is not None
    assert document.provenance.filename is None
    assert document.segments[0].speaker is None
    assert document.content == "Salut"


def test_unknown_and_malformed_conversation_json_is_not_saved(
    store: TutorSqliteStore,
) -> None:
    service = _conversation_service(store)
    cases = [
        b"{",
        b"[]",
        b'"Bonjour"',
        json.dumps(
            {
                "title": "Chat",
                "messages": [{"speaker": "user", "text": "Bonjour"}],
                "account_id": SECRET,
            }
        ).encode(),
        json.dumps(
            {"messages": [{"text": "Bonjour", "email": "secret@example.com"}]}
        ).encode(),
        json.dumps(
            {
                "messages": [{"text": "Bonjour"}],
                "api_key": "sk-secret",
                "attachments": [{"url": SECRET_URL}],
            }
        ).encode(),
        json.dumps({"messages": [{"role": "user", "content": "Bonjour"}]}).encode(),
        json.dumps(
            {
                "title": "ChatGPT",
                "mapping": {"node": {"message": {"content": {"parts": ["Bonjour"]}}}},
            }
        ).encode(),
        json.dumps(
            {
                "messages": [
                    {"speaker": "user", "text": "Bonjour", "timestamp": "yesterday"}
                ]
            }
        ).encode(),
        json.dumps(
            {"messages": [{"text": "Bonjour", "timestamp": "2026-04-01T12:00:00"}]}
        ).encode(),
        b"\xff\xfe",
    ]
    for payload in cases:
        with pytest.raises(Exception, match="会話ログ") as exc:
            service.ingest_conversation(
                source=BytesIO(payload),
                filename="dialogue.json",
                declared_media_type="application/json",
            )
        assert SECRET not in str(exc.value)
        assert "sk-secret" not in str(exc.value)
        assert "secret@example.com" not in str(exc.value)
    assert store.source_documents.list() == []


def test_empty_messages_are_skipped_and_all_empty_is_rejected(
    store: TutorSqliteStore,
) -> None:
    mixed = {
        "messages": [
            {"speaker": "user", "text": ""},
            {"speaker": "partner", "text": "Salut"},
            {"text": "\n\n"},
        ]
    }
    document = (
        _conversation_service(store)
        .ingest_conversation(
            source=BytesIO(json.dumps(mixed).encode()),
            filename="mixed.json",
            declared_media_type="application/json",
        )
        .document
    )
    assert document.content == "Salut"
    assert document.metadata["message_count"] == 1
    assert document.metadata["empty_message_count"] == 2
    assert len(document.segments) == 1

    for payload in (
        {"messages": []},
        {"messages": [{"speaker": "user", "text": "   "}]},
    ):
        with pytest.raises(Exception, match="本文が空"):
            _conversation_service(store).ingest_conversation(
                source=BytesIO(json.dumps(payload).encode()),
                filename="empty.json",
                declared_media_type="application/json",
            )
    assert len(store.source_documents.list()) == 1


def test_same_conversation_reuses_source_and_other_bytes_create_a_new_one(
    store: TutorSqliteStore,
) -> None:
    payload = json.dumps(CONVERSATION, ensure_ascii=False).encode()
    created = _conversation_service(store).ingest_conversation(
        source=BytesIO(payload),
        filename="dialogue.json",
        declared_media_type="application/json",
        title="Fixé",
    )
    reused = _conversation_service(store).ingest_conversation(
        source=BytesIO(payload),
        filename="autre.json",
        declared_media_type="text/plain",
        title="Ignoré",
    )
    assert reused.action is IngestAction.reuse
    assert reused.document.id == created.document.id
    assert reused.document.title == "Fixé"
    assert reused.document.content_hash == created.document.content_hash
    other = json.dumps({"messages": [{"text": "Autre phrase."}]}).encode()
    created_other = _conversation_service(store).ingest_conversation(
        source=BytesIO(other),
        filename="autre.json",
        declared_media_type=None,
    )
    assert created_other.action is IngestAction.create
    assert created_other.document.id != created.document.id


def test_text_and_conversation_sources_survive_database_reopen(tmp_path) -> None:
    path = tmp_path / "tutor.db"
    store = TutorSqliteStore(f"sqlite:///{path}")
    try:
        text = _text_service(store).ingest_text_file(
            source=BytesIO(MARKDOWN.encode()),
            filename="leçon.md",
            declared_media_type="text/markdown",
        )
        conversation = _conversation_service(store).ingest_conversation(
            source=BytesIO(json.dumps(CONVERSATION, ensure_ascii=False).encode()),
            filename="dialogue.json",
            declared_media_type="application/json",
        )
        store.engine.dispose()
        reopened = TutorSqliteStore(f"sqlite:///{path}")
        try:
            loaded_text = reopened.source_documents.get(text.document.id)
            loaded_conversation = reopened.source_documents.get(
                conversation.document.id
            )
            assert loaded_text == text.document
            assert loaded_conversation == conversation.document
            assert loaded_conversation is not None
            assert _span(loaded_conversation, "café").speaker == "partner"
            assert (
                _span(loaded_conversation, "café").timestamp == "2026-04-01T03:00:01Z"
            )
        finally:
            reopened.engine.dispose()
    finally:
        store.engine.dispose()


def test_candidate_evidence_maps_to_conversation_speaker(
    store: TutorSqliteStore,
) -> None:
    document = (
        _conversation_service(store)
        .ingest_conversation(
            source=BytesIO(json.dumps(CONVERSATION, ensure_ascii=False).encode()),
            filename="dialogue.json",
            declared_media_type="application/json",
        )
        .document
    )
    extractor = _CafeExtractor()
    extracted = ExtractionService(extractor).extract(document)
    assert extractor.sources[0].source_type == "conversation_log"
    evidence = read_source_evidence(
        document.content, extracted.candidates[0].evidence_span
    )
    assert evidence == "café"
    mapped = segment_for_span(
        document.segments,
        start=extracted.candidates[0].evidence_span.start,
        end=extracted.candidates[0].evidence_span.end,
    )
    assert mapped.speaker == "partner"
    assert mapped.timestamp == "2026-04-01T03:00:01Z"


def test_invalid_text_and_conversation_inputs_are_rejected(
    store: TutorSqliteStore,
) -> None:
    text = _text_service(store)
    with pytest.raises(Exception, match="空"):
        text.ingest_text_file(
            source=BytesIO(b""),
            filename="notes.txt",
            declared_media_type="text/plain",
        )
    with pytest.raises(Exception, match="本文が空"):
        text.ingest_text_file(
            source=BytesIO(b"   \n\n"),
            filename="notes.md",
            declared_media_type="text/markdown",
        )
    with pytest.raises(Exception, match="読み取れなかった"):
        text.ingest_text_file(
            source=BytesIO(b"\xff\xfeBonjour"),
            filename="notes.txt",
            declared_media_type="text/plain",
        )
    html = b"<!DOCTYPE html><html><body>SUPERSECRET</body></html>"
    with pytest.raises(Exception, match="読み取れなかった"):
        text.ingest_text_file(
            source=BytesIO(html),
            filename="notes.txt",
            declared_media_type="text/plain",
        )
    with pytest.raises(Exception, match="取り込めない"):
        text.ingest_text_file(
            source=BytesIO(b'{"messages":[{"text":"Bonjour"}]}'),
            filename="dialogue.json",
            declared_media_type="application/json",
        )
    with pytest.raises(Exception, match="取り込めない"):
        text.ingest_text_file(
            source=BytesIO(PLAIN.encode()),
            filename="notes.txt",
            declared_media_type="text/html",
        )
    with pytest.raises(Exception, match="上限"):
        text.ingest_text_file(
            source=BytesIO(("あ" * (MAX_SOURCE_TEXT_CHARS + 1)).encode()),
            filename="long.txt",
            declared_media_type="text/plain",
        )
    conversation = _conversation_service(store)
    with pytest.raises(Exception, match="取り込めない"):
        conversation.ingest_conversation(
            source=BytesIO(b"Bonjour"),
            filename="notes.txt",
            declared_media_type="text/plain",
        )
    with pytest.raises(Exception, match="指定が不正"):
        conversation.ingest_conversation(
            source=BytesIO(b'{"messages":[{"text":"Bonjour"}]}'),
            filename=None,
            declared_media_type=None,
        )
    assert store.source_documents.list() == []


def test_ingest_text_file_api_returns_source_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"
    assert manual.json()["source_type"] == "manual_text"

    created = client.post(
        "/api/tutor/sources/ingest/text-file",
        files={"file": ("../../leçon.md", MARKDOWN.encode(), "text/markdown")},
        data={"title": "Mon cours", "note": "depuis le md", "language": "fr"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "create"
    source = body["source"]
    assert source["source_type"] == "conversation_log"
    assert source["title"] == "Mon cours"
    assert source["content"] == MARKDOWN_CONTENT
    assert source["provenance"]["filename"] == "leçon.md"
    assert source["metadata"]["source_format"] == "markdown"
    assert source["metadata"]["note"] == "depuis le md"
    assert SECRET not in created.text
    assert "../" not in created.text

    detail = client.get(f"/api/tutor/sources/{source['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == MARKDOWN_CONTENT
    assert SECRET not in detail.text

    again = client.post(
        "/api/tutor/sources/ingest/text-file",
        files={"file": ("leçon.md", MARKDOWN.encode(), "text/plain")},
    )
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == source["id"]
    assert again.json()["source"]["title"] == "Mon cours"

    app.dependency_overrides[get_learning_item_extractor] = lambda: _CafeExtractor()
    extracted = client.post(f"/api/tutor/sources/{source['id']}/candidates/extract")
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["created"][0]["evidence_text"] == "café"


def test_ingest_conversation_api_distinguishes_errors_and_keeps_manual_create(
    client: TestClient, store: TutorSqliteStore
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "Bonjour\r\n"},
    )
    assert manual.status_code == 201
    assert manual.json()["content"] == "Bonjour\r\n"

    created = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={
            "file": (
                "dialogue.json",
                json.dumps(CONVERSATION, ensure_ascii=False).encode(),
                "application/json",
            )
        },
        data={"language": "fr"},
    )
    assert created.status_code == 201, created.text
    source = created.json()["source"]
    assert source["content"] == CONVERSATION_CONTENT
    assert source["segments"][1]["speaker"] == "partner"
    assert source["segments"][1]["timestamp"] == "2026-04-01T03:00:01Z"
    assert source["segments"][1]["start_seconds"] is None
    detail = client.get(f"/api/tutor/sources/{source['id']}")
    assert detail.json()["metadata"]["empty_message_count"] == 1
    assert "account_id" not in detail.text

    unknown = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={
            "file": (
                "export.json",
                json.dumps(
                    {
                        "messages": [{"text": "Bonjour"}],
                        "account_id": SECRET,
                        "api_key": "sk-secret",
                    }
                ).encode(),
                "application/json",
            )
        },
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "malformed_conversation"
    assert SECRET not in unknown.text
    assert "sk-secret" not in unknown.text

    malformed = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={"file": ("dialogue.json", b"{", "application/json")},
    )
    assert malformed.status_code == 400
    assert malformed.json()["detail"]["code"] == "malformed_conversation"

    empty = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={
            "file": (
                "dialogue.json",
                b'{"messages":[{"text":" "}]}',
                "application/json",
            )
        },
    )
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "conversation_empty"

    wrong = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={"file": ("notes.txt", b"Bonjour", "text/plain")},
    )
    assert wrong.status_code == 415
    assert wrong.json()["detail"]["code"] == "unsupported_media"

    html = client.post(
        "/api/tutor/sources/ingest/text-file",
        files={"file": ("notes.md", MARKDOWN.encode(), "text/html")},
    )
    assert html.status_code == 415

    app.dependency_overrides[get_text_file_ingestion_service] = lambda: (
        TextFileIngestionService(store.source_documents, max_bytes=8)
    )
    too_big = client.post(
        "/api/tutor/sources/ingest/text-file",
        files={"file": ("notes.txt", PLAIN.encode(), "text/plain")},
    )
    assert too_big.status_code == 413
    assert too_big.json()["detail"]["code"] == "file_too_large"

    app.dependency_overrides[get_conversation_ingestion_service] = lambda: (
        ConversationIngestionService(store.source_documents, max_bytes=8)
    )
    conversation_too_big = client.post(
        "/api/tutor/sources/ingest/conversation",
        files={
            "file": (
                "dialogue.json",
                json.dumps(CONVERSATION).encode(),
                "application/json",
            )
        },
    )
    assert conversation_too_big.status_code == 413
    assert conversation_too_big.json()["detail"]["code"] == "file_too_large"
    assert len(store.source_documents.list()) == 2


def test_openapi_exposes_text_and_conversation_ingest() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    text_file = spec["paths"]["/api/tutor/sources/ingest/text-file"]["post"]
    conversation = spec["paths"]["/api/tutor/sources/ingest/conversation"]["post"]
    assert "multipart/form-data" in text_file["requestBody"]["content"]
    assert "multipart/form-data" in conversation["requestBody"]["content"]
    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props
    assert "file" not in create_props
    assert "/api/tutor/sources" in spec["paths"]


def test_text_modules_do_not_fetch() -> None:
    import app.ingestion.conversation_log as conversation
    import app.ingestion.text_file as text_file
    import app.services.conversation_ingestion as conversation_service
    import app.services.text_file_ingestion as text_service

    forbidden = {
        "requests",
        "httpx",
        "urllib",
        "aiohttp",
        "openai",
        "markdown",
        "mistune",
        "bs4",
    }
    for module in (text_file, conversation, text_service, conversation_service):
        assert _imported_roots(module).isdisjoint(forbidden), module.__name__


class _CafeExtractor:
    def __init__(self) -> None:
        self.sources: list[SourceDocument] = []

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.sources.append(source)
        start = source.content.index("café")
        return ExtractorResult(
            candidates=(
                ExtractedCandidate(
                    item_type="vocabulary",
                    canonical_form="café",
                    meaning_ja="コーヒー",
                    evidence_span=ExtractedEvidenceSpan(
                        start=start, end=start + len("café")
                    ),
                    confidence=0.9,
                ),
            ),
            provider="fake",
            model="fake",
            extraction_version="test-v1",
        )


def _text_service(
    store: TutorSqliteStore, *, clock=lambda: FIXED
) -> TextFileIngestionService:
    return TextFileIngestionService(store.source_documents, clock=clock)


def _conversation_service(
    store: TutorSqliteStore, *, clock=lambda: FIXED
) -> ConversationIngestionService:
    return ConversationIngestionService(store.source_documents, clock=clock)


def _span(document: SourceDocument, word: str):
    start = document.content.index(word)
    return segment_for_span(document.segments, start=start, end=start + len(word))


def _assert_slices(document: SourceDocument, pieces: list[str]) -> None:
    for segment, piece in zip(document.segments, pieces, strict=True):
        extracted = document.content[segment.normalized_start : segment.normalized_end]
        assert extracted == piece


def _imported_roots(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
            if node.module.startswith("app."):
                roots.add(".".join(node.module.split(".")[:2]))
    return roots

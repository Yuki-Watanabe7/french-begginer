"""Text Source Ingestion の vertical slice（Issue #125 / Phase 1）。

ユーザーがフランス語本文を貼り付けて保存し、一覧・詳細で読み返し、
SQLite 再 open 後も残ることを HTTP API で通す。LearningItem 抽出と
LLM は行わない。
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.api.tutor import SOURCE_CONTENT_PREVIEW_MAX_CHARS
from app.domain.noun import NOUNS
from app.domain.tutor import SourceDocument
from app.main import app
from app.repositories.sqlite import TutorSqliteStore

SOURCE_TITLE = "Article test"
SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
SOURCE_NOTE = "se rendre compte が気になった"


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _post_source(client: TestClient, **overrides) -> dict:
    payload = {
        "title": SOURCE_TITLE,
        "content": SOURCE_CONTENT,
        "language": "fr",
        "metadata": {"note": SOURCE_NOTE},
    }
    payload.update(overrides)
    res = client.post("/api/tutor/sources", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_phase1_text_ingestion_vertical_slice(tmp_path: Path):
    """必須 vertical slice: 貼り付け保存 → 一覧 → 詳細 → file DB 再 open。

    Phase 1 では LearningItem を抽出せず、SourceDocument の持ち込みと
    読み返しだけを成立させる。
    """
    db_path = tmp_path / "tutor-phase1.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    app.dependency_overrides[get_tutor_store] = lambda: file_store
    try:
        with TestClient(app) as http:
            created = _post_source(http)
            source_id = created["id"]
            assert created["title"] == SOURCE_TITLE
            assert created["content"] == SOURCE_CONTENT
            assert created["source_type"] == "manual_text"
            assert created["language"] == "fr"
            assert created["metadata"]["note"] == SOURCE_NOTE

            listed = http.get("/api/tutor/sources")
            assert listed.status_code == 200, listed.text
            rows = listed.json()
            assert [row["id"] for row in rows] == [source_id]
            assert "content" not in rows[0]
            assert rows[0]["title"] == SOURCE_TITLE
            assert rows[0]["content_preview"] == SOURCE_CONTENT
            assert "note" not in rows[0]

            detail = http.get(f"/api/tutor/sources/{source_id}")
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert body["title"] == SOURCE_TITLE
            assert body["content"] == SOURCE_CONTENT
            assert body["metadata"]["note"] == SOURCE_NOTE

            assert file_store.learning_items.list() == []
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    app.dependency_overrides[get_tutor_store] = lambda: reopened
    try:
        with TestClient(app) as http:
            listed = http.get("/api/tutor/sources")
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [source_id]

            detail = http.get(f"/api/tutor/sources/{source_id}")
            assert detail.status_code == 200
            loaded = detail.json()
            assert loaded["title"] == SOURCE_TITLE
            assert loaded["content"] == SOURCE_CONTENT
            assert loaded["metadata"]["note"] == SOURCE_NOTE
            assert loaded["source_type"] == "manual_text"

            assert reopened.learning_items.list() == []
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase1_newer_source_appears_first(client: TestClient):
    first = _post_source(client, title="first", content="un", metadata={})
    second = _post_source(client, title="second", content="deux", metadata={})

    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == [second["id"], first["id"]]


def test_phase1_list_order_is_stable_for_same_created_at(
    client: TestClient, store: TutorSqliteStore
):
    same_time = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    store.source_documents.create(
        SourceDocument(id="src-b", title="B", content="b", created_at=same_time)
    )
    store.source_documents.create(
        SourceDocument(id="src-a", title="A", content="a", created_at=same_time)
    )
    res = client.get("/api/tutor/sources")
    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == ["src-a", "src-b"]


def test_phase1_missing_source_returns_404(client: TestClient):
    res = client.get("/api/tutor/sources/missing-source")
    assert res.status_code == 404
    assert "SourceDocument" in res.json()["detail"]


def test_phase1_validation_errors(client: TestClient):
    empty_title = client.post(
        "/api/tutor/sources", json={"title": "", "content": SOURCE_CONTENT}
    )
    assert empty_title.status_code == 422

    empty_content = client.post(
        "/api/tutor/sources", json={"title": SOURCE_TITLE, "content": ""}
    )
    assert empty_content.status_code == 422

    extra_type = client.post(
        "/api/tutor/sources",
        json={
            "title": SOURCE_TITLE,
            "content": SOURCE_CONTENT,
            "source_type": "youtube",
        },
    )
    assert extra_type.status_code == 422

    assert client.get("/api/tutor/sources?limit=0").status_code == 422
    assert client.get("/api/tutor/sources?limit=101").status_code == 422


def test_phase1_list_preview_is_truncated(client: TestClient):
    content = "é" * (SOURCE_CONTENT_PREVIEW_MAX_CHARS + 20)
    created = _post_source(client, content=content, metadata={})

    listed = client.get("/api/tutor/sources").json()[0]
    assert listed["id"] == created["id"]
    assert listed["content_preview"] == content[:SOURCE_CONTENT_PREVIEW_MAX_CHARS]
    assert "content" not in listed

    detail = client.get(f"/api/tutor/sources/{created['id']}").json()
    assert detail["content"] == content


def test_phase1_tutor_modules_are_llm_independent():
    import ast
    import inspect

    import app.api.tutor as tutor_api
    import app.services.tutor_service as tutor_service
    from app.domain import tutor as tutor_domain

    forbidden = {"openai", "anthropic", "langchain", "litellm"}

    def imported_top_levels(module: object) -> set[str]:
        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        return names

    for module in (tutor_api, tutor_service, tutor_domain):
        found = imported_top_levels(module) & forbidden
        assert not found, f"{module.__name__} imports {found}"


def test_phase1_has_no_url_pdf_youtube_ingestion_endpoints():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/sources" in paths
    assert "/api/tutor/sources/{source_id}" in paths
    forbidden = (
        "/api/tutor/sources/url",
        "/api/tutor/sources/pdf",
        "/api/tutor/sources/youtube",
        "/api/tutor/ingest",
        "/api/tutor/extract",
    )
    for path in forbidden:
        assert path not in paths, path

    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props
    source_type = spec["components"]["schemas"]["SourceDocument"]["properties"][
        "source_type"
    ]
    assert source_type.get("const") == "manual_text" or source_type.get("enum") == [
        "manual_text"
    ]


def test_phase1_existing_quiz_and_tts_contracts_are_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    question = client.get("/api/questions/next")
    assert question.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(question.json())

    check = client.post(
        "/api/answers/check",
        json={
            "verb": "être",
            "tense": "présent",
            "pronoun": "je",
            "answer": "suis",
        },
    )
    assert check.status_code == 200
    assert check.json()["correct"] is True

    noun = client.get("/api/nouns/next")
    assert noun.status_code == 200
    assert noun.json()["noun"] in NOUNS

    noun_check = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "masculine"},
    )
    assert noun_check.status_code == 200
    assert noun_check.json()["correct"] is True

    article = client.get("/api/nouns/article/next")
    assert article.status_code == 200
    assert "noun" in article.json()

    article_check = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un livre"},
    )
    assert article_check.status_code == 200
    assert article_check.json()["correct"] is True

    tts = client.get("/api/tts/speak?text=bonjour")
    assert tts.status_code == 503
    assert "OPENAI_API_KEY" in tts.json()["detail"]

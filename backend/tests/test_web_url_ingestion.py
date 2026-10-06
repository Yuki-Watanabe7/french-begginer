"""Web URL から SourceDocument を安全に取り込む（Issue #190）。

公開ネットワークは使わない。DNS と TCP 接続は fake に置き換える。
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store, get_web_page_fetcher
from app.domain.source_ingestion import (
    INGESTION_VERSION,
    IngestAction,
    SourceIngestionRequest,
    content_digest,
)
from app.domain.tutor import SourceDocument, read_source_evidence
from app.ingestion.errors import WebFetchErrorCode, WebUrlIngestionError
from app.ingestion.fetcher import (
    MAX_REDIRECTS,
    FetchedWebPage,
    HttpExchange,
    OutboundHttpRequest,
)
from app.ingestion.html_extract import decode_page_text, extract_html
from app.ingestion.stdlib_http import SocketAddressResolver, build_web_page_fetcher
from app.ingestion.url_policy import is_blocked_ip, validate_web_url
from app.ingestion.web_url import WEB_URL_ADAPTER_VERSION, WebUrlIngestionAdapter
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.web_url_ingestion import WebUrlIngestionService

FIXED = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)

ARTICLE_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Le petit déjeuner</title>
  <link rel="canonical" href="https://example.com/articles/petit-dejeuner">
</head>
<body>
  <nav>Accueil Menu Contact</nav>
  <script>var secret = "ne pas extraire";</script>
  <style>.hidden { display: none; }</style>
  <article>
    <h1>Le petit déjeuner</h1>
    <p>Aujourd'hui, l'élève prend un café à l'école.</p>
    <p>Il n'est pas trop tard pour apprendre.</p>
    <p>C'est aujourd\u2019hui que cafe\u0301 reste du café.</p>
  </article>
  <footer>Copyright secret-footer</footer>
</body>
</html>
"""

PUBLIC_URL = "https://example.com/articles/petit-dejeuner"


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


class MapResolver:
    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        if hostname not in self.mapping:
            raise WebUrlIngestionError(
                "URL の名前解決に失敗した",
                code=WebFetchErrorCode.upstream_error,
            )
        return self.mapping[hostname]


class ScriptedTransport:
    def __init__(self, exchanges: list[HttpExchange | Exception]) -> None:
        self._exchanges = list(exchanges)
        self.calls: list[OutboundHttpRequest] = []

    def exchange(self, request: OutboundHttpRequest) -> HttpExchange:
        self.calls.append(request)
        item = self._exchanges.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakePageFetcher:
    def __init__(
        self,
        pages: list[FetchedWebPage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pages = list(pages or [])
        self.error = error
        self.urls: list[str] = []
        self._index = 0

    def fetch(self, url: str, *, fetched_at: datetime) -> FetchedWebPage:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        page = self.pages[self._index]
        if self._index < len(self.pages) - 1:
            self._index += 1
        return page


def test_public_url_fixture_extracts_title_body_and_drops_noise() -> None:
    extracted = extract_html(ARTICLE_HTML)
    assert extracted.title == "Le petit déjeuner"
    assert extracted.canonical_href == "https://example.com/articles/petit-dejeuner"
    body = "\n\n".join(extracted.paragraphs)
    assert body.split("\n\n") == [
        "Le petit déjeuner",
        "Aujourd'hui, l'élève prend un café à l'école.",
        "Il n'est pas trop tard pour apprendre.",
        "C'est aujourd\u2019hui que cafe\u0301 reste du café.",
    ]
    assert "Accueil" not in body
    assert "ne pas extraire" not in body
    assert "secret-footer" not in body
    assert ".hidden" not in body
    assert "<" not in body


def test_html_without_landmark_keeps_paragraph_order_and_skips_nav() -> None:
    html = (
        "<html><head><title>Titre</title></head><body>"
        "<nav>Menu secret</nav>"
        "<p>Première phrase assez longue pour le corps.</p>"
        "<p>Deuxième phrase, l'apostrophe reste.</p>"
        "</body></html>"
    )
    extracted = extract_html(html)
    assert extracted.title == "Titre"
    assert extracted.paragraphs == (
        "Première phrase assez longue pour le corps.",
        "Deuxième phrase, l'apostrophe reste.",
    )


def test_decode_respects_charset_and_does_not_break_accents() -> None:
    body = "café à l'école".encode("iso-8859-1")
    text = decode_page_text(
        body,
        media_type="text/html",
        content_type_header="text/html; charset=iso-8859-1",
    )
    assert text == "café à l'école"
    meta = b"<meta charset='iso-8859-1'><p>" + body
    from_meta = decode_page_text(
        meta, media_type="text/html", content_type_header="text/html"
    )
    assert "café à l'école" in from_meta


def test_url_normalization_and_blocked_literals_hide_private_addresses() -> None:
    normalized = validate_web_url("HTTPS://Example.COM:443/a/b#frag")
    assert normalized.normalized_url == "https://example.com/a/b"
    assert normalized.ip_literal is None

    with_port = validate_web_url("https://example.com:8443/a")
    assert with_port.normalized_url == "https://example.com:8443/a"
    assert with_port.host_header == "example.com:8443"

    idn = validate_web_url("https://café.example/a")
    assert idn.hostname == "xn--caf-dma.example"
    assert idn.normalized_url == "https://xn--caf-dma.example/a"

    for raw in (
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/",
        "http://192.168.0.8/",
        "http://172.16.0.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://localhost/admin",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/",
        "https://example.com\\@127.0.0.1/",
        "http://user:s3cret@example.com/a",
        "file:///etc/passwd",
        "http://example.com/a b",
    ):
        with pytest.raises(WebUrlIngestionError) as caught:
            validate_web_url(raw)
        message = str(caught.value)
        assert "127.0.0.1" not in message
        assert "169.254.169.254" not in message
        assert "10.0.0.1" not in message
        assert "s3cret" not in message
        assert caught.value.code in {
            WebFetchErrorCode.invalid_url,
            WebFetchErrorCode.blocked_url,
        }


def test_public_ip_literal_is_allowed_and_multicast_is_blocked() -> None:
    import ipaddress

    parsed = validate_web_url("http://8.8.8.8/health")
    assert parsed.ip_literal == "8.8.8.8"
    assert parsed.normalized_url == "http://8.8.8.8/health"
    assert is_blocked_ip(ipaddress.ip_address("8.8.8.8")) is False
    assert is_blocked_ip(ipaddress.ip_address("224.0.0.1")) is True
    with pytest.raises(WebUrlIngestionError) as caught:
        validate_web_url("http://224.0.0.1/")
    assert caught.value.code is WebFetchErrorCode.blocked_url
    assert "224.0.0.1" not in str(caught.value)


def test_fetch_pins_resolved_ip_and_keeps_hostname_for_sni() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver({"example.com": ("8.8.8.8",)})
    transport = ScriptedTransport([_html_exchange(ARTICLE_HTML)])
    page = GuardedWebFetcher(resolver, transport).fetch(
        "HTTPS://Example.COM/articles/petit-dejeuner#top",
        fetched_at=FIXED,
    )
    assert page.requested_url == PUBLIC_URL
    assert page.final_url == PUBLIC_URL
    assert page.media_type == "text/html"
    assert resolver.calls == [("example.com", 443)]
    assert transport.calls[0].ip == "8.8.8.8"
    assert transport.calls[0].hostname == "example.com"
    assert transport.calls[0].host_header == "example.com"


def test_redirect_is_revalidated_and_private_targets_are_not_followed() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver(
        {
            "example.com": ("8.8.8.8",),
            "cdn.example.com": ("1.1.1.1",),
        }
    )
    transport = ScriptedTransport(
        [
            HttpExchange(
                status=302,
                headers={"location": "https://cdn.example.com/page"},
                body=b"",
            ),
            _html_exchange(ARTICLE_HTML),
        ]
    )
    page = GuardedWebFetcher(resolver, transport).fetch(
        "https://example.com/start", fetched_at=FIXED
    )
    assert page.requested_url == "https://example.com/start"
    assert page.final_url == "https://cdn.example.com/page"
    assert [call.ip for call in transport.calls] == ["8.8.8.8", "1.1.1.1"]
    assert resolver.calls == [("example.com", 443), ("cdn.example.com", 443)]

    blocked = ScriptedTransport(
        [
            HttpExchange(
                status=302,
                headers={"location": "http://169.254.169.254/latest"},
                body=b"ignore-me",
            )
        ]
    )
    with pytest.raises(WebUrlIngestionError) as private_redirect:
        GuardedWebFetcher(resolver, blocked).fetch(
            "https://example.com/start", fetched_at=FIXED
        )
    assert private_redirect.value.code is WebFetchErrorCode.blocked_url
    assert len(blocked.calls) == 1
    assert "169.254.169.254" not in str(private_redirect.value)
    assert "ignore-me" not in str(private_redirect.value)


def test_dns_answer_containing_a_private_address_is_blocked() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver({"example.com": ("8.8.8.8", "10.1.2.3")})
    transport = ScriptedTransport([_html_exchange(ARTICLE_HTML)])
    with pytest.raises(WebUrlIngestionError) as caught:
        GuardedWebFetcher(resolver, transport).fetch(
            "https://example.com/a", fetched_at=FIXED
        )
    assert caught.value.code is WebFetchErrorCode.blocked_url
    assert transport.calls == []
    assert "10.1.2.3" not in str(caught.value)
    assert "8.8.8.8" not in str(caught.value)


def test_localhost_and_metadata_names_do_not_resolve() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver({})
    transport = ScriptedTransport([])
    for url in ("http://localhost/", "http://metadata.google.internal/"):
        with pytest.raises(WebUrlIngestionError) as caught:
            GuardedWebFetcher(resolver, transport).fetch(url, fetched_at=FIXED)
        assert caught.value.code is WebFetchErrorCode.blocked_url
    assert resolver.calls == []
    assert transport.calls == []


def test_redirect_limit_timeout_upstream_type_and_size() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver({"example.com": ("8.8.8.8",)})
    redirects = [
        HttpExchange(status=302, headers={"location": "/next"}, body=b"")
        for _ in range(MAX_REDIRECTS + 1)
    ]
    with pytest.raises(WebUrlIngestionError) as too_many:
        GuardedWebFetcher(resolver, ScriptedTransport(redirects)).fetch(
            "https://example.com/a", fetched_at=FIXED
        )
    assert too_many.value.code is WebFetchErrorCode.too_many_redirects

    with pytest.raises(WebUrlIngestionError) as timed_out:
        GuardedWebFetcher(resolver, ScriptedTransport([TimeoutError()])).fetch(
            "https://example.com/a", fetched_at=FIXED
        )
    assert timed_out.value.code is WebFetchErrorCode.fetch_timeout
    assert timed_out.value.retryable is True

    for status_code in (404, 503):
        with pytest.raises(WebUrlIngestionError) as upstream:
            GuardedWebFetcher(
                resolver,
                ScriptedTransport(
                    [
                        HttpExchange(
                            status=status_code,
                            headers={"content-type": "text/html"},
                            body=b"secret-body",
                        )
                    ]
                ),
            ).fetch("https://example.com/a", fetched_at=FIXED)
        assert upstream.value.code is WebFetchErrorCode.upstream_error
        assert upstream.value.upstream_status == status_code
        assert "secret-body" not in str(upstream.value)

    with pytest.raises(WebUrlIngestionError) as wrong_type:
        GuardedWebFetcher(
            resolver,
            ScriptedTransport(
                [
                    HttpExchange(
                        status=200,
                        headers={"content-type": "application/pdf"},
                        body=b"%PDF-1.7",
                    )
                ]
            ),
        ).fetch("https://example.com/a", fetched_at=FIXED)
    assert wrong_type.value.code is WebFetchErrorCode.unsupported_content_type
    assert "%PDF" not in str(wrong_type.value)

    with pytest.raises(WebUrlIngestionError) as too_large:
        GuardedWebFetcher(
            resolver,
            ScriptedTransport(
                [
                    HttpExchange(
                        status=200,
                        headers={
                            "content-type": "text/html",
                            "content-length": "1000",
                        },
                        body=b"tiny",
                    )
                ]
            ),
            max_bytes=32,
        ).fetch("https://example.com/a", fetched_at=FIXED)
    assert too_large.value.code is WebFetchErrorCode.response_too_large


def test_ingest_saves_provenance_and_plain_text_for_candidate_extraction(
    store: TutorSqliteStore,
) -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    resolver = MapResolver({"example.com": ("8.8.8.8",)})
    transport = ScriptedTransport([_html_exchange(ARTICLE_HTML)])
    service = WebUrlIngestionService(
        store.source_documents,
        GuardedWebFetcher(resolver, transport),
        clock=lambda: FIXED,
    )
    committed = service.ingest_url(
        url="HTTPS://Example.COM/articles/petit-dejeuner#top",
        note="petit déjeuner",
    )
    document = committed.document
    assert committed.created is True
    assert committed.action is IngestAction.create
    assert document.source_type == "web_url"
    assert document.title == "Le petit déjeuner"
    assert "Accueil" not in document.content
    assert "ne pas extraire" not in document.content
    assert "secret-footer" not in document.content
    assert "Aujourd'hui, l'élève prend un café à l'école." in document.content
    assert "aujourd\u2019hui" in document.content
    assert "cafe\u0301" not in document.content
    assert "café" in document.content
    assert "<" not in document.content
    assert document.content_hash == content_digest(document.content)
    assert document.ingestion_version == INGESTION_VERSION
    assert document.provenance is not None
    assert document.provenance.canonical_locator == PUBLIC_URL
    assert document.provenance.fetched_at == FIXED
    assert document.provenance.ingested_at == FIXED
    assert document.provenance.mime_type == "text/html"
    assert document.provenance.adapter_version == WEB_URL_ADAPTER_VERSION
    assert document.provenance.ingestion_version == INGESTION_VERSION
    assert document.metadata["requested_url"] == PUBLIC_URL
    assert document.metadata["final_url"] == PUBLIC_URL
    assert document.metadata["canonical_url"] == PUBLIC_URL
    assert document.metadata["note"] == "petit déjeuner"
    first = document.segments[0]
    assert document.content[first.normalized_start : first.normalized_end] == (
        "Le petit déjeuner"
    )

    extracted = ExtractionService(_CafeExtractor()).extract(document)
    assert len(extracted.candidates) == 1
    evidence = read_source_evidence(
        document.content, extracted.candidates[0].evidence_span
    )
    assert evidence == "café"
    assert extracted.candidates[0].source_document_id == document.id


def test_same_url_reuses_source_and_changed_body_appends_a_version(
    store: TutorSqliteStore,
) -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    first_html = _article("Première version du texte, assez longue pour rester.")
    second_html = _article("Deuxième version du texte, assez longue pour rester.")
    transport = ScriptedTransport(
        [
            _html_exchange(first_html),
            _html_exchange(first_html),
            _html_exchange(second_html),
        ]
    )
    moments = iter((FIXED, LATER, AFTER))
    service = WebUrlIngestionService(
        store.source_documents,
        GuardedWebFetcher(MapResolver({"example.com": ("8.8.8.8",)}), transport),
        clock=lambda: next(moments),
    )
    created = service.ingest_url(url="HTTPS://Example.COM/a#x")
    reused = service.ingest_url(url="https://example.com/a", title="Ignoré")
    assert reused.created is False
    assert reused.action is IngestAction.reuse
    assert reused.document.id == created.document.id
    assert reused.document.title == created.document.title
    assert reused.document.content == created.document.content

    appended = service.ingest_url(url="https://example.com/a")
    assert appended.created is True
    assert appended.action is IngestAction.append_version
    assert appended.document.id != created.document.id
    assert appended.document.metadata["prior_source_id"] == created.document.id
    assert "Deuxième version" in appended.document.content
    preserved = store.source_documents.get(created.document.id)
    assert preserved is not None
    assert preserved.content == created.document.content
    assert "prior_source_id" not in preserved.metadata


def test_short_or_empty_extraction_is_rejected(store: TutorSqliteStore) -> None:
    from app.ingestion.fetcher import GuardedWebFetcher

    html = (
        "<html><title>Court</title><body>"
        "<nav>menu</nav><script>x</script></body></html>"
    )
    short_html = "<p>" + ("x" * 39) + "</p>"
    service = WebUrlIngestionService(
        store.source_documents,
        GuardedWebFetcher(
            MapResolver({"example.com": ("8.8.8.8",)}),
            ScriptedTransport([_html_exchange(html), _html_exchange(short_html)]),
        ),
        clock=lambda: FIXED,
    )
    with pytest.raises(WebUrlIngestionError) as empty:
        service.ingest_url(url="https://example.com/empty")
    assert empty.value.code is WebFetchErrorCode.extraction_empty
    with pytest.raises(WebUrlIngestionError) as short:
        service.ingest_url(url="https://example.com/short")
    assert short.value.code is WebFetchErrorCode.extraction_empty
    assert store.source_documents.list() == []


def test_title_override_and_plain_text_page(store: TutorSqliteStore) -> None:
    page = FetchedWebPage(
        requested_url=PUBLIC_URL,
        final_url="https://cdn.example.com/articles/petit-dejeuner",
        status_code=200,
        media_type="text/plain",
        content_type_header="text/plain; charset=utf-8",
        body=(
            "Aujourd'hui, l'élève prend un café.\n\n"
            "Il n'est pas trop tard pour apprendre le français."
        ).encode(),
        fetched_at=FIXED,
    )
    committed = WebUrlIngestionService(
        store.source_documents,
        FakePageFetcher([page]),
        clock=lambda: FIXED,
    ).ingest_url(url=PUBLIC_URL, title="Mon titre", note="note")
    assert committed.document.title == "Mon titre"
    assert committed.document.provenance is not None
    assert committed.document.provenance.mime_type == "text/plain"
    assert committed.document.metadata["final_url"].startswith(
        "https://cdn.example.com/"
    )
    assert "Aujourd'hui" in committed.document.content
    assert committed.document.segments[0].external_locator is not None


def test_unsafe_canonical_link_is_dropped() -> None:
    html = ARTICLE_HTML.replace(
        "https://example.com/articles/petit-dejeuner",
        "http://127.0.0.1/secret",
    )
    result = WebUrlIngestionAdapter(FakePageFetcher([_page(html)])).ingest(
        _request(), ingested_at=FIXED
    )
    assert "canonical_url" not in result.metadata
    assert "127.0.0.1" not in str(result.metadata)


def test_relative_canonical_is_resolved() -> None:
    html = ARTICLE_HTML.replace(
        "https://example.com/articles/petit-dejeuner",
        "/articles/petit-dejeuner",
    )
    result = WebUrlIngestionAdapter(FakePageFetcher([_page(html)])).ingest(
        _request(), ingested_at=FIXED
    )
    assert result.metadata["canonical_url"] == PUBLIC_URL


def test_socket_resolver_hides_resolver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror("internal resolver detail")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(WebUrlIngestionError) as caught:
        SocketAddressResolver().resolve("example.com", 443)
    assert caught.value.code is WebFetchErrorCode.upstream_error
    assert "internal resolver detail" not in str(caught.value)


def test_build_web_page_fetcher_uses_guarded_fetcher() -> None:
    from app.ingestion.fetcher import GuardedWebFetcher
    from app.ingestion.stdlib_http import SocketAddressResolver as Resolver
    from app.ingestion.stdlib_http import StdlibHttpTransport

    fetcher = build_web_page_fetcher()
    assert isinstance(fetcher, GuardedWebFetcher)
    assert isinstance(fetcher._resolver, Resolver)
    assert isinstance(fetcher._transport, StdlibHttpTransport)


def test_adapter_boundary_does_not_import_an_http_client() -> None:
    import app.domain.source_ingestion as domain
    import app.ingestion.fetcher as fetcher
    import app.ingestion.html_extract as html_extract
    import app.ingestion.stdlib_http as transport
    import app.ingestion.url_policy as policy
    import app.ingestion.web_url as adapter
    import app.services.source_ingestion_service as commit_service
    import app.services.web_url_ingestion as service

    forbidden = {
        "http",
        "httpx",
        "requests",
        "urllib3",
        "aiohttp",
        "bs4",
        "lxml",
        "trafilatura",
        "readability",
    }
    modules = (
        domain,
        fetcher,
        html_extract,
        policy,
        adapter,
        service,
        commit_service,
    )
    for module in modules:
        assert _imported_roots(module).isdisjoint(forbidden), module.__name__
    assert "http" in _imported_roots(transport)
    assert "httpx" not in _imported_roots(transport)
    assert "urllib" not in _imported_roots(transport)


def test_ingest_url_api_returns_source_detail_and_keeps_manual_create(
    client: TestClient,
) -> None:
    manual = client.post(
        "/api/tutor/sources",
        json={"title": "手入力", "content": "ligne\r\n\r\n\r\nsuite"},
    )
    assert manual.status_code == 201
    assert manual.json()["source_type"] == "manual_text"
    assert manual.json()["content"] == "ligne\r\n\r\n\r\nsuite"

    fetcher = FakePageFetcher([_page(ARTICLE_HTML)])
    app.dependency_overrides[get_web_page_fetcher] = lambda: fetcher
    created = client.post(
        "/api/tutor/sources/ingest/url",
        json={"url": PUBLIC_URL, "note": "depuis le web"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "create"
    assert body["created"] is True
    source = body["source"]
    assert source["source_type"] == "web_url"
    assert source["title"] == "Le petit déjeuner"
    assert "ne pas extraire" not in source["content"]
    assert "café" in source["content"]
    assert source["provenance"]["canonical_locator"] == PUBLIC_URL
    assert source["provenance"]["mime_type"] == "text/html"
    assert source["content_hash"] == content_digest(source["content"])
    assert source["ingestion_version"] == INGESTION_VERSION
    assert source["metadata"]["note"] == "depuis le web"

    detail = client.get(f"/api/tutor/sources/{source['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == source["content"]

    again = client.post("/api/tutor/sources/ingest/url", json={"url": PUBLIC_URL})
    assert again.status_code == 200
    assert again.json()["action"] == "reuse"
    assert again.json()["source"]["id"] == source["id"]

    listed = client.get("/api/tutor/sources")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert source["id"] in ids
    assert manual.json()["id"] in ids
    previews = " ".join(item["content_preview"] for item in listed.json())
    assert "<nav" not in previews
    assert "ne pas extraire" not in previews


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (
            WebUrlIngestionError(
                "URL の形式が不正", code=WebFetchErrorCode.invalid_url
            ),
            400,
        ),
        (
            WebUrlIngestionError(
                "この URL への接続は許可されていない",
                code=WebFetchErrorCode.blocked_url,
            ),
            400,
        ),
        (
            WebUrlIngestionError(
                "ページの取得が時間内に終わらなかった",
                code=WebFetchErrorCode.fetch_timeout,
            ),
            504,
        ),
        (
            WebUrlIngestionError(
                "HTML またはテキスト以外のページは取り込めない",
                code=WebFetchErrorCode.unsupported_content_type,
            ),
            415,
        ),
        (
            WebUrlIngestionError(
                "ページのサイズが上限を超えている",
                code=WebFetchErrorCode.response_too_large,
            ),
            413,
        ),
        (
            WebUrlIngestionError(
                "ページから本文を取り出せなかった",
                code=WebFetchErrorCode.extraction_empty,
            ),
            422,
        ),
        (
            WebUrlIngestionError(
                "ページの取得に失敗した（HTTP 404）",
                code=WebFetchErrorCode.upstream_error,
                upstream_status=404,
            ),
            502,
        ),
        (
            WebUrlIngestionError(
                "リダイレクト回数が上限を超えた",
                code=WebFetchErrorCode.too_many_redirects,
            ),
            502,
        ),
    ],
)
def test_ingest_url_api_distinguishes_errors(
    client: TestClient, error: WebUrlIngestionError, status_code: int
) -> None:
    app.dependency_overrides[get_web_page_fetcher] = lambda: FakePageFetcher(
        error=error
    )
    response = client.post(
        "/api/tutor/sources/ingest/url",
        json={"url": "https://example.com/a"},
    )
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error.code.value
    assert "127.0.0.1" not in response.text
    if error.upstream_status is not None:
        assert response.json()["detail"]["upstream_status"] == 404


def test_ingest_url_api_rejects_credentials_without_fetching(
    client: TestClient,
) -> None:
    fetcher = FakePageFetcher(error=AssertionError("fetched"))
    app.dependency_overrides[get_web_page_fetcher] = lambda: fetcher
    response = client.post(
        "/api/tutor/sources/ingest/url",
        json={"url": "https://user:s3cret@example.com/a"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_url"
    assert "s3cret" not in response.text
    assert fetcher.urls == []


def test_openapi_exposes_url_ingest_without_changing_manual_create() -> None:
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    assert "/api/tutor/sources/ingest/url" in spec["paths"]
    create_props = spec["components"]["schemas"]["CreateSourceRequest"]["properties"]
    assert "source_type" not in create_props
    assert "url" not in create_props


class _CafeExtractor:
    def extract(self, source: SourceDocument) -> ExtractorResult:
        content = source.content
        start = content.index("café")
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


def _html_exchange(html: str) -> HttpExchange:
    return HttpExchange(
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=html.encode(),
    )


def _article(paragraph: str) -> str:
    return (
        "<html><head><title>Article</title></head><body><article><p>"
        + paragraph
        + "</p></article></body></html>"
    )


def _page(html: str) -> FetchedWebPage:
    return FetchedWebPage(
        requested_url=PUBLIC_URL,
        final_url=PUBLIC_URL,
        status_code=200,
        media_type="text/html",
        content_type_header="text/html; charset=utf-8",
        body=html.encode(),
        fetched_at=FIXED,
    )


def _request() -> SourceIngestionRequest:
    return SourceIngestionRequest(source_type="web_url", locator=PUBLIC_URL)


def _imported_roots(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots

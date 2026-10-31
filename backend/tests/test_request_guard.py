"""家庭内本番の Host / Origin / 有料 GET 境界（Issue #219）。

本番 app は CORS を付けず、DNS rebinding・別サイトからの書込・TTS 費用を拒否する。
これは利用者認証ではない（LAN に届く端末は使える）ことも前提として固定する。
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tutor_store
from app.main import create_app
from app.repositories.sqlite import TutorSqliteStore
from app.runtime_settings import RuntimeSettings, parse_allowed_hosts
from app.services.tts_cache_service import TTSCacheService

LAN_HOST = "192.168.1.20:8080"
LAN_ORIGIN = f"http://{LAN_HOST}"
ANSWER = {"verb": "être", "tense": "présent", "pronoun": "je", "answer": "suis"}
TTS_HEADER = {"X-French-Tutor-Request": "1"}


@pytest.fixture(autouse=True)
def isolated_tts_cache(tmp_path, monkeypatch):
    import app.services.tts_service as tts_module

    monkeypatch.setattr(tts_module, "_cache", TTSCacheService(tmp_path / "tts"))


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    settings = RuntimeSettings(
        environment="production",
        allowed_hosts=parse_allowed_hosts("192.168.1.20,french-host.local"),
    )
    app = create_app(settings)
    app.dependency_overrides[get_tutor_store] = lambda: store
    with TestClient(app, base_url=f"http://{LAN_HOST}") as test_client:
        yield test_client


def _fake_openai() -> MagicMock:
    response = MagicMock()
    response.content = b"fake_audio"
    openai = MagicMock()
    openai.return_value.audio.speech.create.return_value = response
    return openai


# --- Host ---


def test_allowed_lan_host_can_read_without_cors_headers(client):
    res = client.get("/api/questions/next", headers={"Origin": "https://evil.example"})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


@pytest.mark.parametrize("host", ["french-host.local:8080", "localhost:8080"])
def test_other_allowed_and_loopback_hosts_pass(client, host):
    res = client.get("/health", headers={"Host": host})
    assert res.status_code == 200


def test_unknown_host_is_rejected_even_for_health(client):
    res = client.get("/health", headers={"Host": "attacker.example:8080"})
    assert res.status_code == 400
    assert res.json() == {"detail": "Host is not allowed"}


def test_dns_rebinding_write_is_rejected_by_host(client, store):
    """rebinding 後のブラウザは攻撃者ホスト名で同一オリジンになるため Host で止める。"""
    res = client.post(
        "/api/tutor/sources",
        json={"title": "x", "content": "Bonjour."},
        headers={
            "Host": "attacker.example:8080",
            "Origin": "http://attacker.example:8080",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert res.status_code == 400
    assert store.source_documents.list() == []


# --- 書込の Origin / Fetch Metadata ---


def test_same_origin_write_is_allowed(client):
    res = client.post("/api/answers/check", json=ANSWER, headers={"Origin": LAN_ORIGIN})
    assert res.status_code == 200
    assert res.json()["correct"] is True


def test_same_origin_write_by_fetch_metadata_only_is_allowed(client):
    """localhost / HTTPS ではブラウザが Sec-Fetch-Site を付ける。"""
    res = client.post(
        "/api/answers/check", json=ANSWER, headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert res.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.example"},
        {"Origin": "http://192.168.1.20:5173"},
        {"Origin": "null"},
        {"Origin": LAN_ORIGIN, "Sec-Fetch-Site": "cross-site"},
        {"Origin": LAN_ORIGIN, "Sec-Fetch-Site": "same-site"},
        {},
    ],
    ids=["cross-site", "other-port", "opaque", "fetch-cross", "fetch-site", "none"],
)
def test_cross_or_unverified_origin_write_is_rejected(client, store, headers):
    res = client.post(
        "/api/tutor/sources",
        json={"title": "x", "content": "Bonjour."},
        headers=headers,
    )
    assert res.status_code == 403
    assert store.source_documents.list() == []


def test_same_origin_tutor_write_reaches_store(client, store):
    res = client.post(
        "/api/tutor/sources",
        json={"title": "合成データ", "content": "Bonjour."},
        headers={"Origin": LAN_ORIGIN},
    )
    assert res.status_code == 201, res.text
    assert len(store.source_documents.list()) == 1


def test_cross_origin_preflight_gets_no_cors_permission(client):
    res = client.options(
        "/api/answers/check",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code >= 400
    assert "access-control-allow-origin" not in res.headers


# --- 有料 GET（TTS） ---


def test_tts_without_client_header_is_rejected_before_openai(client, monkeypatch):
    """`<audio src>` は独自ヘッダーを付けられない。平文 HTTP では Origin も来ない。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    openai = _fake_openai()
    with patch("app.services.tts_service.OpenAI", openai):
        res = client.get("/api/tts/speak?text=un+livre")
    assert res.status_code == 403
    openai.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_tts_from_other_site_is_rejected_even_with_header(client, monkeypatch, headers):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    openai = _fake_openai()
    with patch("app.services.tts_service.OpenAI", openai):
        res = client.get("/api/tts/speak?text=un+livre", headers=TTS_HEADER | headers)
    assert res.status_code == 403
    openai.assert_not_called()


def test_tts_from_app_client_is_allowed(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    openai = _fake_openai()
    with patch("app.services.tts_service.OpenAI", openai):
        res = client.get("/api/tts/speak?text=un+livre", headers=TTS_HEADER)
    assert res.status_code == 200
    assert res.content == b"fake_audio"
    openai.assert_called_once()


# --- 起動 ---


def test_production_startup_opens_store():
    """権限不足や新しすぎる schema を最初のリクエストではなく起動時に失敗させる。"""
    opened: list[bool] = []
    app = create_app(RuntimeSettings(environment="production"))
    app.dependency_overrides[get_tutor_store] = lambda: opened.append(True)
    with TestClient(app, base_url="http://localhost:8080"):
        assert opened == [True]


def test_production_startup_fails_when_store_cannot_open():
    def broken_store():
        raise PermissionError("DB directory is not writable")

    app = create_app(RuntimeSettings(environment="production"))
    app.dependency_overrides[get_tutor_store] = broken_store
    with pytest.raises(PermissionError):
        with TestClient(app, base_url="http://localhost:8080"):
            pass


# --- development は従来どおり ---


def test_development_keeps_cors_and_skips_host_check():
    app = create_app(RuntimeSettings(environment="development"))
    with TestClient(app) as dev_client:
        res = dev_client.get(
            "/api/questions/next",
            headers={"Host": "anything.example", "Origin": "http://localhost:5173"},
        )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "*"

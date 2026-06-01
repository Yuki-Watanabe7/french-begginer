import hashlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tts_cache_service import TTSCacheService

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """テストごとに独立した一時キャッシュディレクトリを使用し、テスト間の干渉を防ぐ"""
    import app.services.tts_service as tts_module

    cache = TTSCacheService(tmp_path / "tts")
    monkeypatch.setattr(tts_module, "_cache", cache)
    return cache


# --- 既存テスト ---


def test_tts_missing_api_key(monkeypatch):
    """APIキー未設定かつキャッシュなし時に503を返す"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.get("/api/tts/speak?text=un+livre")
    assert res.status_code == 503
    assert "OPENAI_API_KEY" in res.json()["detail"]


def test_tts_empty_text(monkeypatch):
    """空テキストに400を返す"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    res = client.get("/api/tts/speak?text=")
    assert res.status_code == 400


def test_tts_text_too_long(monkeypatch):
    """501文字以上のテキストに400を返す"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    res = client.get(f"/api/tts/speak?text={'a' * 501}")
    assert res.status_code == 400


def test_tts_success(monkeypatch):
    """正常なリクエストに200とaudio/mpegを返す"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_audio = b"fake_audio_data"

    mock_response = MagicMock()
    mock_response.content = fake_audio

    mock_openai = MagicMock()
    mock_openai.return_value.audio.speech.create.return_value = mock_response

    with patch("app.services.tts_service.OpenAI", mock_openai):
        res = client.get("/api/tts/speak?text=un+livre")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == fake_audio
    mock_openai.return_value.audio.speech.create.assert_called_once_with(
        model="tts-1",
        voice="alloy",
        input="un livre",
    )


def test_tts_default_text(monkeypatch):
    """textパラメータ省略時はデフォルト 'un livre' を使用"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_audio = b"fake_audio_data"

    mock_response = MagicMock()
    mock_response.content = fake_audio
    mock_openai = MagicMock()
    mock_openai.return_value.audio.speech.create.return_value = mock_response

    with patch("app.services.tts_service.OpenAI", mock_openai):
        res = client.get("/api/tts/speak")

    assert res.status_code == 200
    mock_openai.return_value.audio.speech.create.assert_called_once_with(
        model="tts-1",
        voice="alloy",
        input="un livre",
    )


# --- キャッシュ機能テスト ---


def test_cache_key_format():
    """キャッシュキーが tts:provider:model:voice:{sha256} の形式で生成される"""
    cache = TTSCacheService()
    key = cache.make_cache_key("un livre")
    expected_hash = hashlib.sha256(b"un livre").hexdigest()
    assert key == f"tts:openai:tts-1:alloy:{expected_hash}"


def test_cache_key_components():
    """キャッシュキーにprovider/model/voice/textハッシュが含まれる"""
    cache = TTSCacheService()
    key = cache.make_cache_key(
        "bonjour", provider="openai", model="tts-1", voice="alloy"
    )
    parts = key.split(":")
    assert len(parts) == 5
    assert parts[0] == "tts"
    assert parts[1] == "openai"
    assert parts[2] == "tts-1"
    assert parts[3] == "alloy"
    assert len(parts[4]) == 64  # sha256 hex digest


def test_cache_key_differs_by_text():
    """異なるテキストからは異なるキャッシュキーが生成される"""
    cache = TTSCacheService()
    key1 = cache.make_cache_key("un livre")
    key2 = cache.make_cache_key("une table")
    assert key1 != key2


def test_cache_miss_calls_openai(monkeypatch, isolated_cache):
    """キャッシュミス時にOpenAI APIを呼び出し、結果をキャッシュに保存する"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_audio = b"cached_audio"

    mock_response = MagicMock()
    mock_response.content = fake_audio
    mock_openai = MagicMock()
    mock_openai.return_value.audio.speech.create.return_value = mock_response

    with patch("app.services.tts_service.OpenAI", mock_openai):
        res = client.get("/api/tts/speak?text=bonjour")

    assert res.status_code == 200
    assert res.content == fake_audio
    mock_openai.return_value.audio.speech.create.assert_called_once()
    assert isolated_cache.get("bonjour") == fake_audio


def test_cache_hit_skips_openai(monkeypatch, isolated_cache):
    """キャッシュヒット時はOpenAI APIを呼ばずに保存済み音声を返す"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_audio = b"pre_cached_audio"
    isolated_cache.set("bonjour", fake_audio)

    mock_openai = MagicMock()
    with patch("app.services.tts_service.OpenAI", mock_openai):
        res = client.get("/api/tts/speak?text=bonjour")

    assert res.status_code == 200
    assert res.content == fake_audio
    mock_openai.assert_not_called()


def test_cache_hit_returns_audio_mpeg(monkeypatch, isolated_cache):
    """キャッシュヒット時もaudio/mpegとして音声バイナリが返る"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    isolated_cache.set("merci", b"audio_bytes")

    res = client.get("/api/tts/speak?text=merci")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/mpeg")
    assert res.content == b"audio_bytes"


def test_cache_miss_then_hit(monkeypatch, isolated_cache):
    """1回目はキャッシュミスでAPI呼び出し、2回目はキャッシュヒットでAPIを呼ばない"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_audio = b"audio_for_au_revoir"

    mock_response = MagicMock()
    mock_response.content = fake_audio
    mock_openai = MagicMock()
    mock_openai.return_value.audio.speech.create.return_value = mock_response

    with patch("app.services.tts_service.OpenAI", mock_openai):
        res1 = client.get("/api/tts/speak?text=au+revoir")

    assert res1.status_code == 200
    mock_openai.return_value.audio.speech.create.assert_called_once()

    # 2回目はキャッシュヒット（APIキーなし・API呼び出しなし）
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_openai2 = MagicMock()
    with patch("app.services.tts_service.OpenAI", mock_openai2):
        res2 = client.get("/api/tts/speak?text=au+revoir")

    assert res2.status_code == 200
    assert res2.content == fake_audio
    mock_openai2.assert_not_called()

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_tts_missing_api_key(monkeypatch):
    """APIキー未設定時に503を返す"""
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

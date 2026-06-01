import os

from openai import APIConnectionError, AuthenticationError, OpenAI

from app.services.tts_cache_service import TTSCacheService

_cache = TTSCacheService()


def generate_tts_audio(text: str) -> bytes:
    """
    OpenAI TTS APIを呼び出してフランス語テキストを音声（audio/mpeg）に変換する。
    生成した音声はファイルシステムにキャッシュし、同一テキストへの再リクエストではAPIを呼ばない。
    OPENAI_API_KEY未設定でもキャッシュが存在すれば音声を返せる。
    """
    if not text or not text.strip():
        raise ValueError("Text must not be empty")

    if len(text) > 500:
        raise ValueError("Text is too long (max 500 characters)")

    cached = _cache.get(text)
    if cached is not None:
        return cached

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OSError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)
    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text,
        )
    except AuthenticationError as e:
        raise OSError("OPENAI_API_KEY is invalid") from e
    except APIConnectionError as e:
        raise RuntimeError("Failed to connect to OpenAI API") from e

    audio = response.content
    _cache.set(text, audio)
    return audio

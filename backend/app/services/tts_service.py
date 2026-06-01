import os

from openai import APIConnectionError, AuthenticationError, OpenAI


def generate_tts_audio(text: str) -> bytes:
    """
    OpenAI TTS APIを呼び出してフランス語テキストを音声（audio/mpeg）に変換する。

    キャッシュキー案（後続issueで実装時に使用）:
        key = f"tts:openai:tts-1:alloy:{hashlib.sha256(text.encode()).hexdigest()}"
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OSError("OPENAI_API_KEY is not set")

    if not text or not text.strip():
        raise ValueError("Text must not be empty")

    if len(text) > 500:
        raise ValueError("Text is too long (max 500 characters)")

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

    return response.content

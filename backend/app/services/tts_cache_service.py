import hashlib
import os
from pathlib import Path


class TTSCacheService:
    """ファイルシステムベースのTTS音声キャッシュ

    置き場所は TTS_CACHE_DIR（本番はコードを読取専用にするため専用 volume）、
    未指定時は backend/.cache/tts。
    """

    def __init__(self, cache_dir: "Path | str | None" = None):
        if cache_dir is None:
            cache_dir = os.environ.get("TTS_CACHE_DIR") or (
                Path(__file__).parent.parent.parent / ".cache" / "tts"
            )
        self.cache_dir = Path(cache_dir)

    def make_cache_key(
        self,
        text: str,
        *,
        provider: str = "openai",
        model: str = "tts-1",
        voice: str = "alloy",
    ) -> str:
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"tts:{provider}:{model}:{voice}:{text_hash}"

    def _key_to_path(self, key: str) -> Path:
        return self.cache_dir / (key.replace(":", "_") + ".mp3")

    def get(self, text: str) -> "bytes | None":
        path = self._key_to_path(self.make_cache_key(text))
        if path.exists():
            return path.read_bytes()
        return None

    def set(self, text: str, audio: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._key_to_path(self.make_cache_key(text))
        path.write_bytes(audio)

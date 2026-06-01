import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.tts_service import generate_tts_audio

router = APIRouter(prefix="/api/tts", tags=["tts"])

_DEFAULT_TEXTS = ["un livre", "une maison", "l'école"]


@router.get("/speak")
def speak(
    text: str = Query(default="un livre", description="読み上げるフランス語テキスト"),
) -> StreamingResponse:
    """
    フランス語テキストをOpenAI TTS APIで音声化し、audio/mpegとして返す。

    レスポンス形式: audio/mpeg バイナリ（StreamingResponse）
    Frontend再生方法:
        1. <audio src="/api/tts/speak?text=un+livre" controls />  ← シンプル
        2. fetch() → Blob URL → new Audio(blobUrl).play()         ← プログラム制御向き
    どちらも動作確認済み。ボタン連打防止が必要な場合はBlob URL方式を推奨。

    エラー時:
        503: APIキー未設定または無効
        400: テキストが空、または500文字超
        502: OpenAI APIへの接続失敗
    """
    try:
        audio_data = generate_tts_audio(text)
    except OSError as e:
        raise HTTPException(
            status_code=503,
            detail=f"TTS service unavailable: {e}",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"TTS API call failed: {e}",
        ) from e

    return StreamingResponse(
        io.BytesIO(audio_data),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )

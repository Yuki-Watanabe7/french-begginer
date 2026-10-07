"""pypdf による text layer 抽出（Issue #191）。

OCR ライブラリは import しない。画像だけの PDF はここではテキストにしない。
タイムアウトは解析の区切り（開く前、開いた後、各ページの前）で見る。
1 ページの `extract_text` 自体は中断しない。ファイルサイズとページ上限が
その処理量の境界になる。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from io import BytesIO

import pypdf
from pypdf import PdfReader

from app.ingestion.pdf_errors import (
    MSG_ENCRYPTED_PDF,
    MSG_MALFORMED_PDF,
    MSG_PARSER_TIMEOUT,
    MSG_TOO_MANY_PAGES,
    PdfIngestErrorCode,
    PdfIngestionError,
)
from app.ingestion.pdf_text import (
    MAX_PDF_PAGES,
    PDF_PARSE_TIMEOUT_SECONDS,
    PdfExtractedDocument,
    PdfPageText,
)

PARSER_NAME = "pypdf"
TEXT_EXTRACTION_MODE = "plain"


class PypdfTextParser:
    """text layer だけをページ順に読む。パスワードは受け取らない。"""

    def __init__(
        self,
        *,
        max_pages: int = MAX_PDF_PAGES,
        timeout_seconds: float = PDF_PARSE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_pages = max_pages
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    def parse(self, data: bytes) -> PdfExtractedDocument:
        started = self._clock()
        deadline = started + self._timeout_seconds
        try:
            self._check(deadline)
            reader = PdfReader(BytesIO(data))
            self._check(deadline)
            pdf_access = _open_if_needed(reader)
            page_count = len(reader.pages)
            if page_count <= 0:
                raise PdfIngestionError(
                    MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
                )
            if page_count > self._max_pages:
                raise PdfIngestionError(
                    MSG_TOO_MANY_PAGES, code=PdfIngestErrorCode.too_many_pages
                )
            pages: list[PdfPageText] = []
            for index, page in enumerate(reader.pages, start=1):
                self._check(deadline)
                extracted = page.extract_text(extraction_mode=TEXT_EXTRACTION_MODE)
                pages.append(PdfPageText(page_number=index, text=extracted or ""))
            return PdfExtractedDocument(
                page_count=page_count,
                pages=tuple(pages),
                parser_name=PARSER_NAME,
                parser_version=pypdf.__version__,
                pdf_access=pdf_access,
            )
        except PdfIngestionError:
            raise
        except Exception:
            raise PdfIngestionError(
                MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
            ) from None

    def _check(self, deadline: float) -> None:
        if self._clock() > deadline:
            raise PdfIngestionError(
                MSG_PARSER_TIMEOUT, code=PdfIngestErrorCode.parser_timeout
            )


def _open_if_needed(reader: PdfReader) -> str:
    """ユーザーパスワード付きは拒否する。空パスワードで開く制限付きは許可する。"""

    if not reader.is_encrypted:
        return "open"
    try:
        opened = reader.decrypt("")
    except Exception:
        raise PdfIngestionError(
            MSG_ENCRYPTED_PDF, code=PdfIngestErrorCode.encrypted_pdf
        ) from None
    if int(opened) == 0:
        raise PdfIngestionError(
            MSG_ENCRYPTED_PDF, code=PdfIngestErrorCode.encrypted_pdf
        )
    return "owner_restrictions"

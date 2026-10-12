"""PDF 取り込みの失敗分類（Issue #191）。

メッセージは利用者向けで、PDF 本文やパスワードは含めない。
OCR が必要なファイルを、別の成功コードにしない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class PdfIngestErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_pdf = "invalid_pdf"
    malformed_pdf = "malformed_pdf"
    encrypted_pdf = "encrypted_pdf"
    unsupported_media = "unsupported_media"
    file_too_large = "file_too_large"
    too_many_pages = "too_many_pages"
    text_too_large = "text_too_large"
    ocr_required = "ocr_required"
    parser_timeout = "parser_timeout"


_KIND_BY_CODE: dict[PdfIngestErrorCode, IngestionFailureKind] = {
    PdfIngestErrorCode.invalid_pdf: IngestionFailureKind.validation,
    PdfIngestErrorCode.malformed_pdf: IngestionFailureKind.validation,
    PdfIngestErrorCode.encrypted_pdf: IngestionFailureKind.validation,
    PdfIngestErrorCode.unsupported_media: IngestionFailureKind.unsupported_media,
    PdfIngestErrorCode.file_too_large: IngestionFailureKind.input_too_large,
    PdfIngestErrorCode.too_many_pages: IngestionFailureKind.input_too_large,
    PdfIngestErrorCode.text_too_large: IngestionFailureKind.input_too_large,
    PdfIngestErrorCode.ocr_required: IngestionFailureKind.unsupported_media,
    PdfIngestErrorCode.parser_timeout: IngestionFailureKind.timeout,
}


class PdfIngestionError(SourceIngestionError):
    """PDF の検証、解析、本文抽出のいずれかで拒否した。"""

    def __init__(self, message: str, *, code: PdfIngestErrorCode) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code


MSG_INVALID_PDF = "PDF の指定が不正"
MSG_EMPTY_FILE = "ファイルが空"
MSG_FILENAME = "ファイル名が不正"
MSG_MALFORMED_PDF = "PDF を読み取れなかった"
MSG_ENCRYPTED_PDF = "パスワード付き PDF は取り込めない"
MSG_UNSUPPORTED_MEDIA = "PDF 以外のファイルは取り込めない"
MSG_FILE_TOO_LARGE = "PDF のサイズが上限を超えている"
MSG_TOO_MANY_PAGES = "PDF のページ数が上限を超えている"
MSG_TEXT_TOO_LARGE = "PDF から取り出した本文が上限を超えている"
MSG_OCR_REQUIRED = "テキストレイヤーが十分でないため取り込めない。OCR は行わない"
MSG_PARSER_TIMEOUT = "PDF の解析が時間内に終わらなかった"

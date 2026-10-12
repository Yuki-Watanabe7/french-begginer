"""PDF 取り込みの純テキスト規則（Issue #191）。

パーサ実装はここへ import しない。マジックナンバー、ファイル名、
ページ本文の決定的な整形だけを持つ。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from app.domain.source_ingestion import MAX_SHORT_FIELD_CHARS
from app.ingestion.pdf_errors import (
    MSG_EMPTY_FILE,
    MSG_FILE_TOO_LARGE,
    MSG_FILENAME,
    MSG_INVALID_PDF,
    MSG_MALFORMED_PDF,
    MSG_UNSUPPORTED_MEDIA,
    PdfIngestErrorCode,
    PdfIngestionError,
)

PDF_ADAPTER_VERSION = "pdf-text-v1"
MAX_PDF_BYTES = 8_000_000
MAX_PDF_PAGES = 50
PDF_PARSE_TIMEOUT_SECONDS = 10.0
MIN_PDF_LETTER_CHARS = 20
PDF_HEADER_SCAN_BYTES = 1024
PDF_MAGIC = b"%PDF-"

_ACCEPTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    }
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class PdfPageText:
    """1 ページ分の、パーサが返した text layer。空ページも含む。"""

    page_number: int
    text: str


@dataclass(frozen=True)
class PdfExtractedDocument:
    """パーサ境界の出力。バイト列は持たない。"""

    page_count: int
    pages: tuple[PdfPageText, ...]
    parser_name: str
    parser_version: str
    pdf_access: str


class PdfTextParser(Protocol):
    """text layer の抽出。OCR 実装はこの Protocol の裏に置かない。"""

    def parse(self, data: bytes) -> PdfExtractedDocument: ...


def file_digest(data: bytes) -> str:
    """生ファイルのダイジェスト。保存はせず、再投入の locator に使う。"""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def has_pdf_magic(data: bytes) -> bool:
    """先頭 1024 バイト以内の `%PDF-` だけを PDF とみなす。拡張子は見ない。"""

    return PDF_MAGIC in data[:PDF_HEADER_SCAN_BYTES]


def read_bounded(source: BinaryIO, limit: int) -> bytes:
    """上限を 1 バイト超えたところで読み止める。"""

    data = source.read(limit + 1)
    if not isinstance(data, bytes):
        raise PdfIngestionError(MSG_INVALID_PDF, code=PdfIngestErrorCode.invalid_pdf)
    if len(data) > limit:
        raise PdfIngestionError(
            MSG_FILE_TOO_LARGE, code=PdfIngestErrorCode.file_too_large
        )
    return data


def canonical_media_type(value: str | None) -> str | None:
    """`type/subtype` だけを残す。パラメータと大小文字は捨てる。"""

    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def ensure_pdf_media_type(value: str | None) -> None:
    """宣言された MIME が PDF 系でなければ拒否する。未指定はマジック判定に任せる。"""

    media = canonical_media_type(value)
    if media is None or media in _ACCEPTED_MEDIA_TYPES:
        return
    raise PdfIngestionError(
        MSG_UNSUPPORTED_MEDIA, code=PdfIngestErrorCode.unsupported_media
    )


def sanitize_pdf_filename(filename: str | None) -> str:
    """パスを捨て、制御文字を除いた basename だけを metadata に残す。"""

    if filename is None or not filename.strip():
        raise PdfIngestionError(MSG_FILENAME, code=PdfIngestErrorCode.invalid_pdf)
    basename = filename.replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", basename).strip()
    cleaned = unicodedata.normalize("NFC", cleaned)
    if cleaned in {"", ".", ".."}:
        raise PdfIngestionError(MSG_FILENAME, code=PdfIngestErrorCode.invalid_pdf)
    if len(cleaned) > MAX_SHORT_FIELD_CHARS:
        cleaned = cleaned[:MAX_SHORT_FIELD_CHARS].rstrip()
    if not cleaned:
        raise PdfIngestionError(MSG_FILENAME, code=PdfIngestErrorCode.invalid_pdf)
    return cleaned


def normalize_pdf_page_text(text: str) -> str:
    """ページ抽出直後の決定的な整形。共有正規化の前段。

    - 改ページは改行にする
    - 行内の連続した空白は 1 つに畳む
    - 前後の空行だけ除く。ページ内の空行（段落）は残す
    - ハイフン改行は結合しない
    - ヘッダー / フッターは除去しない
    - 合字とアポストロフィは置換しない。NFC は共有正規化が行う
    """

    if "\x00" in text:
        raise PdfIngestionError(
            MSG_MALFORMED_PDF, code=PdfIngestErrorCode.malformed_pdf
        )
    text = text.replace("\f", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def count_letters(text: str) -> int:
    """Unicode の文字（L*）だけを数える。ページ番号などの数字は含めない。"""

    return sum(1 for char in text if unicodedata.category(char).startswith("L"))


def ensure_nonempty_file(data: bytes) -> None:
    if not data:
        raise PdfIngestionError(MSG_EMPTY_FILE, code=PdfIngestErrorCode.invalid_pdf)


def filename_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot <= 0:
        return ""
    return filename[dot:].lower()

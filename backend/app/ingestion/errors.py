"""Web URL 取り込みの失敗分類（Issue #190）。

メッセージは利用者向けで、解決した private IP や応答本文は含めない。
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.source_ingestion import IngestionFailureKind, SourceIngestionError


class WebFetchErrorCode(StrEnum):
    """API が利用者へ区別して返す失敗コード。"""

    invalid_url = "invalid_url"
    blocked_url = "blocked_url"
    fetch_timeout = "fetch_timeout"
    unsupported_content_type = "unsupported_content_type"
    response_too_large = "response_too_large"
    extraction_empty = "extraction_empty"
    upstream_error = "upstream_error"
    too_many_redirects = "too_many_redirects"


_KIND_BY_CODE: dict[WebFetchErrorCode, IngestionFailureKind] = {
    WebFetchErrorCode.invalid_url: IngestionFailureKind.validation,
    WebFetchErrorCode.blocked_url: IngestionFailureKind.validation,
    WebFetchErrorCode.fetch_timeout: IngestionFailureKind.timeout,
    WebFetchErrorCode.unsupported_content_type: IngestionFailureKind.unsupported_media,
    WebFetchErrorCode.response_too_large: IngestionFailureKind.input_too_large,
    WebFetchErrorCode.extraction_empty: IngestionFailureKind.validation,
    WebFetchErrorCode.upstream_error: IngestionFailureKind.provider,
    WebFetchErrorCode.too_many_redirects: IngestionFailureKind.validation,
}


class WebUrlIngestionError(SourceIngestionError):
    """URL の検証、取得、本文抽出のいずれかで拒否した。"""

    def __init__(
        self,
        message: str,
        *,
        code: WebFetchErrorCode,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message, kind=_KIND_BY_CODE[code])
        self.code = code
        self.upstream_status = upstream_status


MSG_INVALID_URL = "URL の形式が不正"
MSG_BLOCKED_URL = "この URL への接続は許可されていない"
MSG_FETCH_TIMEOUT = "ページの取得が時間内に終わらなかった"
MSG_UNSUPPORTED_TYPE = "HTML またはテキスト以外のページは取り込めない"
MSG_RESPONSE_TOO_LARGE = "ページのサイズが上限を超えている"
MSG_EXTRACTION_EMPTY = "ページから本文を取り出せなかった"
MSG_UPSTREAM = "ページの取得に失敗した"
MSG_TOO_MANY_REDIRECTS = "リダイレクト回数が上限を超えた"
MSG_DNS_FAILED = "URL の名前解決に失敗した"


def upstream_failure(status_code: int) -> WebUrlIngestionError:
    """origin の 4xx / 5xx。応答本文はメッセージに載せない。"""

    return WebUrlIngestionError(
        f"{MSG_UPSTREAM}（HTTP {status_code}）",
        code=WebFetchErrorCode.upstream_error,
        upstream_status=status_code,
    )

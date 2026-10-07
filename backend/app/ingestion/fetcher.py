"""URL 取得の境界（Issue #190）。

`GuardedWebFetcher` はリダイレクトのたびに URL と解決済み IP を再検査し、
接続先 IP を transport へ渡す。transport はホスト名で再解決しない。
これにより、検査後に DNS が private IP へ変わる再束縛を接続へ通さない。
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urljoin

from app.domain.source_ingestion import WEB_URL_MEDIA_TYPES
from app.ingestion.errors import (
    MSG_BLOCKED_URL,
    MSG_DNS_FAILED,
    MSG_FETCH_TIMEOUT,
    MSG_RESPONSE_TOO_LARGE,
    MSG_TOO_MANY_REDIRECTS,
    MSG_UNSUPPORTED_TYPE,
    MSG_UPSTREAM,
    WebFetchErrorCode,
    WebUrlIngestionError,
    upstream_failure,
)
from app.ingestion.url_policy import ParsedWebUrl, is_blocked_ip, validate_web_url

MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 10.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class FetchedWebPage:
    """取得済みの応答。本文抽出前のバイト列で、HTML のまま保存しない。"""

    requested_url: str
    final_url: str
    status_code: int
    media_type: str
    content_type_header: str
    body: bytes
    fetched_at: datetime


@dataclass(frozen=True)
class OutboundHttpRequest:
    """検査済みの 1 リクエスト。`ip` は接続先、`hostname` は Host / SNI。"""

    scheme: str
    hostname: str
    ip: str
    port: int
    host_header: str
    target: str


@dataclass(frozen=True)
class HttpExchange:
    status: int
    headers: Mapping[str, str]
    body: bytes


class AddressResolver(Protocol):
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]: ...


class HttpTransport(Protocol):
    def exchange(self, request: OutboundHttpRequest) -> HttpExchange: ...


class WebPageFetcher(Protocol):
    def fetch(self, url: str, *, fetched_at: datetime) -> FetchedWebPage: ...


class GuardedWebFetcher:
    """SSRF 検査を通したあとだけ transport を呼ぶ fetcher。"""

    def __init__(
        self,
        resolver: AddressResolver,
        transport: HttpTransport,
        *,
        max_redirects: int = MAX_REDIRECTS,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._max_redirects = max_redirects
        self._max_bytes = max_bytes

    def fetch(self, url: str, *, fetched_at: datetime) -> FetchedWebPage:
        first = validate_web_url(url)
        current = first
        for hop in range(self._max_redirects + 1):
            pinned_ip = self._public_ips(current)[0]
            try:
                exchange = self._transport.exchange(_outbound(current, pinned_ip))
            except WebUrlIngestionError:
                raise
            except TimeoutError as exc:
                raise WebUrlIngestionError(
                    MSG_FETCH_TIMEOUT, code=WebFetchErrorCode.fetch_timeout
                ) from exc
            except OSError as exc:
                raise WebUrlIngestionError(
                    MSG_UPSTREAM, code=WebFetchErrorCode.upstream_error
                ) from exc
            headers = {key.lower(): value for key, value in exchange.headers.items()}
            if exchange.status in _REDIRECT_STATUSES:
                if hop == self._max_redirects:
                    raise WebUrlIngestionError(
                        MSG_TOO_MANY_REDIRECTS,
                        code=WebFetchErrorCode.too_many_redirects,
                    )
                location = _redirect_location(headers, exchange.status)
                current = validate_web_url(urljoin(current.normalized_url, location))
                continue
            if not 200 <= exchange.status < 300:
                raise upstream_failure(exchange.status)
            self._reject_oversized(headers, exchange.body)
            media_type = _media_type(headers.get("content-type", ""))
            if media_type not in WEB_URL_MEDIA_TYPES:
                raise WebUrlIngestionError(
                    MSG_UNSUPPORTED_TYPE,
                    code=WebFetchErrorCode.unsupported_content_type,
                )
            return FetchedWebPage(
                requested_url=first.normalized_url,
                final_url=current.normalized_url,
                status_code=exchange.status,
                media_type=media_type,
                content_type_header=headers.get("content-type", media_type),
                body=exchange.body,
                fetched_at=fetched_at,
            )
        raise WebUrlIngestionError(
            MSG_TOO_MANY_REDIRECTS,
            code=WebFetchErrorCode.too_many_redirects,
        )

    def _public_ips(self, parsed: ParsedWebUrl) -> tuple[str, ...]:
        if parsed.ip_literal is not None:
            ips = (parsed.ip_literal,)
        else:
            try:
                ips = self._resolver.resolve(parsed.hostname, parsed.port)
            except WebUrlIngestionError:
                raise
            except TimeoutError as exc:
                raise WebUrlIngestionError(
                    MSG_FETCH_TIMEOUT, code=WebFetchErrorCode.fetch_timeout
                ) from exc
            except OSError as exc:
                raise WebUrlIngestionError(
                    MSG_DNS_FAILED, code=WebFetchErrorCode.upstream_error
                ) from exc
        if not ips:
            raise WebUrlIngestionError(
                MSG_DNS_FAILED, code=WebFetchErrorCode.upstream_error
            )
        for ip_text in ips:
            try:
                parsed_ip = ipaddress.ip_address(ip_text)
            except ValueError as exc:
                raise WebUrlIngestionError(
                    MSG_UPSTREAM, code=WebFetchErrorCode.upstream_error
                ) from exc
            if is_blocked_ip(parsed_ip):
                raise WebUrlIngestionError(
                    MSG_BLOCKED_URL, code=WebFetchErrorCode.blocked_url
                )
        return ips

    def _reject_oversized(self, headers: Mapping[str, str], body: bytes) -> None:
        declared = _content_length(headers.get("content-length"))
        if declared is not None and declared > self._max_bytes:
            raise WebUrlIngestionError(
                MSG_RESPONSE_TOO_LARGE, code=WebFetchErrorCode.response_too_large
            )
        if len(body) > self._max_bytes:
            raise WebUrlIngestionError(
                MSG_RESPONSE_TOO_LARGE, code=WebFetchErrorCode.response_too_large
            )


def _outbound(parsed: ParsedWebUrl, ip: str) -> OutboundHttpRequest:
    return OutboundHttpRequest(
        scheme=parsed.scheme,
        hostname=parsed.hostname,
        ip=ip,
        port=parsed.port,
        host_header=parsed.host_header,
        target=parsed.target,
    )


def _redirect_location(headers: Mapping[str, str], status_code: int) -> str:
    location = headers.get("location", "").strip()
    if not location or any(
        character.isspace() or ord(character) < 32 for character in location
    ):
        raise upstream_failure(status_code)
    return location


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        length = int(value.strip())
    except ValueError:
        return None
    if length < 0:
        return None
    return length

"""標準ライブラリだけで IP を固定して HTTP を取得する（Issue #190）。

接続は `OutboundHttpRequest.ip` に対して行う。Host と TLS の SNI は
元のホスト名のままにする。リダイレクトは追わず、呼び出し側が再検査する。
"""

from __future__ import annotations

import http.client
import socket
import ssl

from app.ingestion.errors import (
    MSG_DNS_FAILED,
    MSG_FETCH_TIMEOUT,
    MSG_RESPONSE_TOO_LARGE,
    MSG_UPSTREAM,
    WebFetchErrorCode,
    WebUrlIngestionError,
)
from app.ingestion.fetcher import (
    FETCH_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    GuardedWebFetcher,
    HttpExchange,
    OutboundHttpRequest,
)

USER_AGENT = "FrenchBeginnerSourceIngest/1.0"
_READ_CHUNK_BYTES = 65_536
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class SocketAddressResolver:
    """`socket.getaddrinfo` の結果を、検査前の IP 文字列として返す。"""

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        try:
            infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise WebUrlIngestionError(
                MSG_DNS_FAILED, code=WebFetchErrorCode.upstream_error
            ) from exc
        ips: list[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        if not ips:
            raise WebUrlIngestionError(
                MSG_DNS_FAILED, code=WebFetchErrorCode.upstream_error
            )
        return tuple(ips)


class StdlibHttpTransport:
    """1 リクエストだけ送り、自動リダイレクトも接続の再利用もしない。"""

    def __init__(
        self,
        *,
        timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
        max_bytes: int = MAX_RESPONSE_BYTES,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._user_agent = user_agent

    def exchange(self, request: OutboundHttpRequest) -> HttpExchange:
        connection: http.client.HTTPConnection | None = None
        try:
            connection = self._connect(request)
            connection.request(
                "GET",
                request.target,
                headers={
                    "Host": request.host_header,
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = _first_headers(response.getheaders())
            if response.status in _REDIRECT_STATUSES or 300 <= response.status < 400:
                response.close()
                return HttpExchange(status=response.status, headers=headers, body=b"")
            length = _content_length(headers.get("content-length"))
            if length is not None and length > self._max_bytes:
                response.close()
                raise WebUrlIngestionError(
                    MSG_RESPONSE_TOO_LARGE,
                    code=WebFetchErrorCode.response_too_large,
                )
            body = _read_capped(response, self._max_bytes)
            return HttpExchange(status=response.status, headers=headers, body=body)
        except WebUrlIngestionError:
            raise
        except TimeoutError as exc:
            raise WebUrlIngestionError(
                MSG_FETCH_TIMEOUT, code=WebFetchErrorCode.fetch_timeout
            ) from exc
        except (http.client.HTTPException, ssl.SSLError, OSError) as exc:
            raise WebUrlIngestionError(
                MSG_UPSTREAM, code=WebFetchErrorCode.upstream_error
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    def _connect(self, request: OutboundHttpRequest) -> http.client.HTTPConnection:
        raw = socket.create_connection(
            (request.ip, request.port), timeout=self._timeout
        )
        raw.settimeout(self._timeout)
        try:
            if request.scheme == "https":
                context = ssl.create_default_context()
                tls = context.wrap_socket(raw, server_hostname=request.hostname)
                tls.settimeout(self._timeout)
                connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                    request.hostname,
                    request.port,
                    timeout=self._timeout,
                    context=context,
                )
                connection.sock = tls
                return connection
            connection = http.client.HTTPConnection(
                request.hostname,
                request.port,
                timeout=self._timeout,
            )
            connection.sock = raw
            return connection
        except Exception:
            raw.close()
            raise


def build_web_page_fetcher() -> GuardedWebFetcher:
    """本番の fetcher。テストは fake の resolver / transport を注入する。"""

    return GuardedWebFetcher(
        resolver=SocketAddressResolver(),
        transport=StdlibHttpTransport(),
    )


def _first_headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in pairs:
        lowered = key.lower()
        if lowered not in headers:
            headers[lowered] = value
    return headers


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


def _read_capped(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise WebUrlIngestionError(
                MSG_RESPONSE_TOO_LARGE, code=WebFetchErrorCode.response_too_large
            )
        chunks.append(chunk)
    return b"".join(chunks)

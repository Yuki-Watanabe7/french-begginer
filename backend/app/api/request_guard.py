"""家庭内本番の同一オリジン境界（Issue #219）。

本番は nginx が React と `/api` を同じオリジンで配信するため CORS を使わない。
このミドルウェアはブラウザ経由の悪用（別サイトからの送信、DNS rebinding）を拒否する。
利用者認証ではない。LAN に到達した端末は全機能と API 費用を使える。

- Host: 許可したホスト名（と loopback）以外は 400。
  DNS rebinding では攻撃者のホスト名が届く
- 書込（GET / HEAD / OPTIONS 以外）: Origin か Sec-Fetch-Site で
  同一オリジンと示せなければ 403
- 有料 GET（TTS）: 加えて独自ヘッダーを要求する。`<audio src>` やフォームは
  独自ヘッダーを付けられず、別オリジンの fetch は preflight が CORS 不許可で失敗する

平文 HTTP の LAN IP にはブラウザが Sec-Fetch-* を送らないため、Fetch Metadata は
届いたときだけ検証し、それだけを根拠にしない。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PAID_PATH_PREFIXES = ("/api/tts/",)
CLIENT_HEADER = "x-french-tutor-request"
CLIENT_HEADER_VALUE = "1"


@dataclass(frozen=True)
class GuardRejection:
    status_code: int
    detail: str


def evaluate_request(
    *,
    method: str,
    path: str,
    headers: Headers,
    allowed_hosts: frozenset[str],
) -> GuardRejection | None:
    """要求を通すなら None、拒否するなら理由を返す。"""
    host = headers.get("host", "").strip().lower()
    if _hostname(host) not in allowed_hosts:
        return GuardRejection(400, "Host is not allowed")

    is_paid = path.startswith(PAID_PATH_PREFIXES)
    if method.upper() in SAFE_METHODS and not is_paid:
        return None

    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() != "same-origin":
        return GuardRejection(403, "Cross-origin request is not allowed")

    origin = headers.get("origin")
    if origin is not None and not _is_same_origin(origin, host):
        return GuardRejection(403, "Cross-origin request is not allowed")

    if is_paid:
        if headers.get(CLIENT_HEADER) != CLIENT_HEADER_VALUE:
            return GuardRejection(403, "Paid API requires the app client header")
        return None

    if fetch_site is None and origin is None:
        return GuardRejection(403, "Request origin could not be verified")
    return None


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        rejection = evaluate_request(
            method=scope["method"],
            path=scope["path"],
            headers=headers,
            allowed_hosts=self.allowed_hosts,
        )
        if rejection is None:
            await self.app(scope, receive, send)
            return

        # query string は TTS 本文などを含みうるので記録しない
        logger.warning(
            "request rejected: %s %s host=%r origin=%r reason=%s",
            scope["method"],
            scope["path"],
            headers.get("host"),
            headers.get("origin"),
            rejection.detail,
        )
        response = JSONResponse(
            {"detail": rejection.detail}, status_code=rejection.status_code
        )
        await response(scope, receive, send)


def _hostname(host: str) -> str:
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def _is_same_origin(origin: str, host: str) -> bool:
    parts = urlsplit(origin.strip().lower())
    return parts.scheme in ("http", "https") and parts.netloc == host

"""Web URL の形と接続先の判定（Issue #190）。

DNS の問い合わせはしない。名前解決結果の検査は fetcher が
`is_blocked_ip` に渡す。判定は文字列の prefix だけに頼らず、
IP リテラル（十進・八進・十六進・IPv4-mapped IPv6）も IP として読む。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.domain.source_ingestion import MAX_LOCATOR_CHARS
from app.ingestion.errors import (
    MSG_BLOCKED_URL,
    MSG_INVALID_URL,
    WebFetchErrorCode,
    WebUrlIngestionError,
)

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_OBFUSCATED_IPV4 = re.compile(r"(?i)(?:\d+|0x[0-9a-f]+)(?:\.(?:\d+|0x[0-9a-f]+)){0,3}")
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.goog",
    }
)
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".localdomain",
    ".intranet",
    ".lan",
)


@dataclass(frozen=True)
class ParsedWebUrl:
    """正規化済み URL と、接続に使うホスト情報。"""

    normalized_url: str
    scheme: str
    hostname: str
    port: int
    host_header: str
    target: str
    ip_literal: str | None


def validate_web_url(url: str) -> ParsedWebUrl:
    """http(s) URL を正規化する。危険な接続先は名前解決の前に拒否する。"""

    if not isinstance(url, str):
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)
    stripped = url.strip()
    if not stripped or len(stripped) > MAX_LOCATOR_CHARS or "\\" in stripped:
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)
    if any(_is_forbidden_character(character) for character in stripped):
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)

    try:
        parsed = urlsplit(stripped)
        port = parsed.port
    except ValueError as exc:
        raise WebUrlIngestionError(
            MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url
        ) from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)
    if port == 0:
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)

    raw_host = parsed.hostname
    if raw_host is None:
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)
    hostname = _ascii_hostname(raw_host)
    if not hostname or "%" in hostname:
        raise WebUrlIngestionError(MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url)

    ip = _ip_literal(hostname)
    if ip is not None:
        if is_blocked_ip(ip):
            raise WebUrlIngestionError(
                MSG_BLOCKED_URL, code=WebFetchErrorCode.blocked_url
            )
        host = str(ip)
        ip_literal = host
    else:
        if not _is_public_dns_name(hostname):
            if _looks_like_dns_name(hostname) and (
                "." not in hostname or _is_blocked_hostname(hostname)
            ):
                raise WebUrlIngestionError(
                    MSG_BLOCKED_URL, code=WebFetchErrorCode.blocked_url
                )
            raise WebUrlIngestionError(
                MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url
            )
        if _is_blocked_hostname(hostname):
            raise WebUrlIngestionError(
                MSG_BLOCKED_URL, code=WebFetchErrorCode.blocked_url
            )
        host = hostname
        ip_literal = None

    resolved_port = port if port is not None else (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    target = path if not parsed.query else f"{path}?{parsed.query}"
    bracketed = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    if resolved_port == default_port:
        netloc = bracketed
        host_header = bracketed
    else:
        netloc = f"{bracketed}:{resolved_port}"
        host_header = netloc
    normalized = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return ParsedWebUrl(
        normalized_url=normalized,
        scheme=scheme,
        hostname=host,
        port=resolved_port,
        host_header=host_header,
        target=target,
        ip_literal=ip_literal,
    )


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """loopback / private / link-local / metadata 帯など、公開宛先でないアドレス。"""

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_multicast
        or ip.is_unspecified
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_private
        or not ip.is_global
    )


def _is_forbidden_character(character: str) -> bool:
    code = ord(character)
    return character.isspace() or code < 32 or code == 127


def _ascii_hostname(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WebUrlIngestionError(
            MSG_INVALID_URL, code=WebFetchErrorCode.invalid_url
        ) from exc


def _ip_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip is not None:
        return ip
    if not _OBFUSCATED_IPV4.fullmatch(hostname):
        return None
    try:
        packed = socket.inet_aton(hostname)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


def _is_blocked_hostname(hostname: str) -> bool:
    return hostname in _BLOCKED_HOSTS or hostname.endswith(_BLOCKED_SUFFIXES)


def _looks_like_dns_name(hostname: str) -> bool:
    labels = hostname.split(".")
    return all(_DNS_LABEL.fullmatch(label) for label in labels if label)


def _is_public_dns_name(hostname: str) -> bool:
    labels = hostname.split(".")
    if len(labels) < 2:
        return False
    if not all(_DNS_LABEL.fullmatch(label) for label in labels):
        return False
    return not _is_blocked_hostname(hostname)

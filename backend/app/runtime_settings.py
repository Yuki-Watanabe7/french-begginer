"""実行環境の設定（Issue #219）。

環境変数:
  APP_ENV            development（既定）/ production
  APP_ALLOWED_HOSTS  production でブラウザが開くホスト名。カンマ区切り、ポートなし
                     localhost / 127.0.0.1 / [::1] は常に許可する

development は従来どおり CORS 全許可・Host 検証なし。
production は compose.production.yml から起動し、CORS を使わず
request guard を有効にする。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

AppEnvironment = Literal["development", "production"]

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})

_ENVIRONMENTS: tuple[AppEnvironment, ...] = ("development", "production")


@dataclass(frozen=True)
class RuntimeSettings:
    environment: AppEnvironment = "development"
    allowed_hosts: frozenset[str] = LOOPBACK_HOSTS

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_runtime_settings(environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    """環境変数から設定を読む。不正値は起動時に止める（本番で黙って緩めない）。"""
    env = os.environ if environ is None else environ
    raw_environment = env.get("APP_ENV", "development").strip().lower()
    if raw_environment not in _ENVIRONMENTS:
        raise ValueError(
            f"APP_ENV は {' / '.join(_ENVIRONMENTS)} のいずれか: {raw_environment!r}"
        )
    environment: AppEnvironment = raw_environment  # type: ignore[assignment]
    hosts = parse_allowed_hosts(env.get("APP_ALLOWED_HOSTS", ""))
    return RuntimeSettings(environment=environment, allowed_hosts=hosts)


def parse_allowed_hosts(raw: str) -> frozenset[str]:
    """`192.168.1.20,french-host.local` を正規化する。loopback は常に含める。"""
    hosts: set[str] = set(LOOPBACK_HOSTS)
    for entry in raw.split(","):
        host = entry.strip().lower()
        if not host:
            continue
        if host == "*" or any(char in host for char in "*:/@ "):
            raise ValueError(
                "APP_ALLOWED_HOSTS はポートやスキームを含まないホスト名だけを"
                f"カンマ区切りで指定する: {entry.strip()!r}"
            )
        hosts.add(host)
    return frozenset(hosts)

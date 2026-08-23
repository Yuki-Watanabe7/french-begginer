"""Tutor永続化の接続設定。

環境変数:
  TUTOR_DATABASE_URL  SQLAlchemy URL（最優先）
  TUTOR_DATA_DIR      SQLiteファイルを置くディレクトリ。未指定時は backend/data

デフォルトは `sqlite:///<backend>/data/tutor.db`。
テストでは URL を明示して temporary / in-memory DB を使う。
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _BACKEND_ROOT / "data"
DEFAULT_DB_FILENAME = "tutor.db"


def default_sqlite_path() -> Path:
    data_dir = Path(os.environ.get("TUTOR_DATA_DIR", DEFAULT_DATA_DIR))
    return data_dir / DEFAULT_DB_FILENAME


def get_database_url(url: str | None = None) -> str:
    """解決済みの SQLAlchemy URL を返す。"""
    if url:
        return url
    env_url = os.environ.get("TUTOR_DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{default_sqlite_path()}"

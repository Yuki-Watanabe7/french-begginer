"""Tutor永続化の接続設定。

環境変数:
  TUTOR_DATABASE_URL  SQLAlchemy URL（最優先）
  TUTOR_DATA_DIR      SQLiteファイルを置くディレクトリ。未指定時は backend/data

デフォルトは `sqlite:///<backend>/data/tutor.db`。
テストでは URL を明示して temporary / in-memory DB を使う。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _BACKEND_ROOT / "data"
DEFAULT_DB_FILENAME = "tutor.db"
PRODUCTION_DATA_DIR = Path("/var/lib/french-tutor")


def is_production() -> bool:
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def is_production_volume(name: str) -> bool:
    return (
        re.fullmatch(r"french-production-tutor-data(?:-restored-[a-zA-Z0-9_-]+)?", name)
        is not None
    )


def default_sqlite_path() -> Path:
    data_dir = Path(os.environ.get("TUTOR_DATA_DIR", DEFAULT_DATA_DIR))
    return data_dir / DEFAULT_DB_FILENAME


def get_database_url(url: str | None = None) -> str:
    """解決済みの SQLAlchemy URL を返す。"""
    if is_production():
        if not is_production_volume(
            os.environ.get("TUTOR_VOLUME_NAME", "french-production-tutor-data")
        ):
            raise ValueError("本番専用または復元済みの volume 名を指定してください")
        expected = f"sqlite:///{PRODUCTION_DATA_DIR / DEFAULT_DB_FILENAME}"
        if os.environ.get("TUTOR_DATABASE_URL"):
            raise ValueError("本番では TUTOR_DATABASE_URL を空にしてください")
        if Path(os.environ.get("TUTOR_DATA_DIR", "")) != PRODUCTION_DATA_DIR:
            raise ValueError("本番の TUTOR_DATA_DIR が固定の保存先と異なります")
        if url is not None and url != expected:
            raise ValueError("本番 DB の接続先は変更できません")
        return expected
    if url:
        return url
    env_url = os.environ.get("TUTOR_DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{default_sqlite_path()}"

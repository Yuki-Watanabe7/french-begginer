"""永続化層の日時エンコード。

SQLite の DateTime はタイムゾーンを保持しないため、UTC の ISO 8601 文字列
（microseconds + `+00:00`）として保存する。この形式なら文字列比較が
時系列順と一致し、`due_at <= now` の判定を SQL 側で行える。
"""

from datetime import UTC, datetime

ISO_FORMAT_SPEC = "microseconds"


def require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("永続化する datetime は timezone-aware である必要がある")
    return dt.astimezone(UTC)


def dump_utc(dt: datetime) -> str:
    return require_aware(dt).isoformat(timespec=ISO_FORMAT_SPEC)


def load_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)

"""公開 Snapshot の書き出し（Issue #221）。CLI は scripts/export_public_snapshot.py。

DB は読み取り専用で開き、変更しない。家庭内本番の DB は直接読まず、
scripts/production_backup.sh で取った整合コピーを渡す。

出力は Git 作業ツリーの外の新しいディレクトリに snapshot.json だけを置く。
通常の commit や CI artifact に混ざらないようにするためで、外部への送信や
公開はしない（公開は #223 で本人の承認後に行う）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.domain.public_snapshot import (
    PublicSnapshotAllowlist,
    PublicSnapshotError,
    build_public_snapshot,
    describe_validation_error,
    render_allowlist_draft,
    render_public_snapshot,
)
from app.domain.tutor import utcnow
from app.repositories.sqlite import read_learning_items_readonly

SNAPSHOT_FILENAME = "snapshot.json"


@dataclass(frozen=True)
class PublicSnapshotExport:
    path: Path
    card_count: int
    sha256: str


def default_output_dir(now: datetime | None = None) -> Path:
    stamp = (now or utcnow()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "FrenchTutorSnapshots" / f"public-{stamp}"


def check_output_dir(out: Path) -> Path:
    """新しいディレクトリで、Git 作業ツリーの外であることを確かめる。"""
    target = out.expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise PublicSnapshotError(
            f"出力先が既にある。古いファイルと混ぜないよう新しい場所にする: {target}"
        )
    for parent in target.parents:
        if (parent / ".git").exists():
            raise PublicSnapshotError(
                f"出力先が Git 作業ツリーの中にある。commit に混ぜないよう外に置く: "
                f"{parent}"
            )
    return target


def load_allowlist(path: Path) -> PublicSnapshotAllowlist:
    try:
        return PublicSnapshotAllowlist.model_validate_json(
            path.expanduser().read_bytes()
        )
    except ValidationError as exc:
        raise PublicSnapshotError(
            f"allowlist が不正: {describe_validation_error(exc)}"
        ) from None


def _check_database(database: Path) -> Path:
    path = database.expanduser()
    if not path.is_file() or path.is_symlink():
        raise PublicSnapshotError(f"DB ファイルがない: {path}")
    return path


def draft_allowlist(database: Path) -> str:
    """allowlist の下書き（JSON 文字列）。公開しないものは本人が消す。"""
    items = read_learning_items_readonly(_check_database(database))
    return render_allowlist_draft(items)


def export_public_snapshot(
    *,
    database: Path,
    allowlist: Path,
    out: Path,
    now: datetime | None = None,
) -> PublicSnapshotExport:
    """allowlist の Item だけを snapshot.json に書き出す。失敗時は何も作らない。"""
    target = check_output_dir(out)
    snapshot = build_public_snapshot(
        load_allowlist(allowlist),
        read_learning_items_readonly(_check_database(database)),
        generated_at=now or utcnow(),
    )
    data = render_public_snapshot(snapshot).encode("utf-8")
    target.mkdir(parents=True)
    path = target / SNAPSHOT_FILENAME
    with path.open("xb") as stream:
        stream.write(data)
    return PublicSnapshotExport(
        path=path,
        card_count=len(snapshot.cards),
        sha256=hashlib.sha256(data).hexdigest(),
    )

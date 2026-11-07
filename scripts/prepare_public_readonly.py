#!/usr/bin/env python3
"""検査済みの閲覧専用画面と公開候補教材だけを配布フォルダーにする（#223）。

先に frontend で npm run build:readonly を実行する。DB を開かず、通信も行わない。
生成物の内容と公開先について本人の承認を得てから、別の操作で配布する。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.public_snapshot import (  # noqa: E402
    PublicSnapshot,
    PublicSnapshotError,
    describe_validation_error,
    render_public_snapshot,
)
from app.services.public_snapshot_export import check_output_dir  # noqa: E402

VIEWER_DIR = ROOT / "frontend" / "dist-readonly"
SYNTHETIC = ROOT / "docs" / "operations" / "public-snapshot.synthetic.json"


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PublicSnapshotError("教材の JSON に重複したキーがある")
        result[key] = value
    return result


def prepare_bundle(*, snapshot: Path, out: Path) -> tuple[Path, str, int]:
    """許可したファイルだけを新しい Git 作業ツリー外の場所へコピーする。"""
    target = check_output_dir(out)
    data = snapshot.expanduser().read_bytes()
    payload = json.loads(data, object_pairs_hook=unique_object)
    try:
        parsed = PublicSnapshot.model_validate_json(data)
    except ValidationError as exc:
        raise PublicSnapshotError(
            f"教材の形式が不正: {describe_validation_error(exc)}"
        ) from None
    # Viewer と同じく、任意項目の null、UTC 秒単位以外の日時も拒否する。
    if payload != json.loads(render_public_snapshot(parsed)) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["generated_at"]
    ):
        raise PublicSnapshotError("教材は public-v1 の省略項目・UTC 秒単位の形式にする")

    if VIEWER_DIR.is_symlink() or not VIEWER_DIR.is_dir():
        raise PublicSnapshotError("閲覧専用画面を npm run build:readonly で生成する")
    files: dict[str, Path] = {}
    for path in VIEWER_DIR.rglob("*"):
        name = path.relative_to(VIEWER_DIR).as_posix()
        if path.is_symlink():
            raise PublicSnapshotError("閲覧専用の生成物にリンクがある")
        if path.is_dir() and name == "assets":
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise PublicSnapshotError("閲覧専用の生成物に通常ファイル以外がある")
        if name not in {"index.html", "snapshot.json"} and not re.fullmatch(
            r"assets/index-[A-Za-z0-9_-]+\.js", name
        ):
            raise PublicSnapshotError("閲覧専用の生成物に許可外のファイルがある")
        files[name] = path
    if not {"index.html", "snapshot.json"}.issubset(files) or len(files) != 3:
        raise PublicSnapshotError("閲覧専用の HTML・JS・合成教材の3ファイルが必要")
    if json.loads(files["snapshot.json"].read_bytes()) != json.loads(
        SYNTHETIC.read_bytes()
    ):
        raise PublicSnapshotError("閲覧専用画面の入力が合成教材ではない。再ビルドする")

    # 検査・コピーが完了するまで配布先を作らない。既存の版には触れない。
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as staging:
        stage = Path(staging) / "bundle"
        (stage / "assets").mkdir(parents=True)
        for name, path in files.items():
            if name != "snapshot.json":
                shutil.copyfile(path, stage / name)
        (stage / "snapshot.json").write_bytes(data)
        (stage / ".nojekyll").touch()
        if target.exists():
            raise PublicSnapshotError("出力先が既にある")
        stage.rename(target)
    return target, hashlib.sha256(data).hexdigest(), len(parsed.cards)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target, digest, count = prepare_bundle(snapshot=args.snapshot, out=args.out)
    except (OSError, ValueError) as exc:
        # JSONDecodeError は入力の値を表示しない。
        message = "JSON が不正" if isinstance(exc, json.JSONDecodeError) else str(exc)
        print(f"配布準備失敗: {message}", file=sys.stderr)
        return 1
    print(f"公開候補を作成: {target}（{count} 枚）")
    print(f"snapshot.json sha256: {digest}")
    for path in sorted(target.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(target)} ({path.stat().st_size} bytes)")
    print(
        "外部には送信していません。内容と公開先を本人が承認してから配布してください。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

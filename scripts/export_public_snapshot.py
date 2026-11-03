#!/usr/bin/env python3
"""外出先 Read-Only 向けの公開 Snapshot を書き出す（Issue #221）。

本人が一般公開してよいと選んだ LearningItem だけを snapshot.json にする。
DB は読み取り専用で開き、外部へは何も送らない。家庭内本番の DB は
`bash scripts/production_backup.sh` で取ったコピーを --database に渡す。

使い方（backend ディレクトリから）:

    uv run python ../scripts/export_public_snapshot.py draft \\
        --database ~/FrenchTutorBackups/tutor-<時刻>.db \\
        > ~/FrenchTutorSnapshots/allowlist.json
    # allowlist.json から一般公開しないものを消す
    uv run python ../scripts/export_public_snapshot.py export \\
        --database ~/FrenchTutorBackups/tutor-<時刻>.db \\
        --allowlist ~/FrenchTutorSnapshots/allowlist.json

手順と項目の一覧は docs/operations/remote-readonly-contract.md。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.public_snapshot_export import (  # noqa: E402
    default_output_dir,
    draft_allowlist,
    export_public_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="許可した教材だけを外出先閲覧用の snapshot.json に書き出す"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser(
        "draft", help="allowlist の下書きを標準出力へ出す（suspended 以外の全 Item）"
    )
    draft.add_argument("--database", type=Path, required=True, help="SQLite ファイル")

    export = commands.add_parser("export", help="allowlist の Item だけを書き出す")
    export.add_argument("--database", type=Path, required=True, help="SQLite ファイル")
    export.add_argument(
        "--allowlist", type=Path, required=True, help="公開を許可する Item の JSON"
    )
    export.add_argument(
        "--out",
        type=Path,
        default=None,
        help="新しい出力ディレクトリ。Git 作業ツリーの外。"
        "省略時は ~/FrenchTutorSnapshots/public-<時刻>",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "draft":
            sys.stdout.write(draft_allowlist(args.database))
            print(
                "下書きです。一般公開してよい Item だけを残してください。",
                file=sys.stderr,
            )
            return 0
        result = export_public_snapshot(
            database=args.database,
            allowlist=args.allowlist,
            out=args.out or default_output_dir(),
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"{args.command} 失敗: {exc}", file=sys.stderr)
        return 1
    print(f"書き出しました: {result.path}（{result.card_count} 枚）")
    print(f"sha256: {result.sha256}")
    print(
        "外部へは送信していません。公開前に中身を読み、一般公開してよい内容か確認してください。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

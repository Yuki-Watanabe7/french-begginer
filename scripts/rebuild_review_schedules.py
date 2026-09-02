#!/usr/bin/env python3
"""ReviewSchedule の不整合検出と再構築（Issue #166）。

LearningEvent 履歴を source of truth として、欠損や旧 scheduler_version の
schedule を現行 baseline（v1-directional）へ再計算する。
due queue 取得時には使わない。明示的な maintenance 操作用。

使い方（backend ディレクトリから）:

    uv run python ../scripts/rebuild_review_schedules.py --check
    uv run python ../scripts/rebuild_review_schedules.py --item-id <id>
    uv run python ../scripts/rebuild_review_schedules.py --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.repositories.sqlite import TutorSqliteStore  # noqa: E402
from app.services.review_schedule_rebuilder import (  # noqa: E402
    ReviewScheduleRebuilder,
    build_review_schedule_rebuilder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LearningEvent 履歴から ReviewSchedule を点検・再構築する"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="不整合を検出するだけ。schedule は書き換えない",
    )
    parser.add_argument(
        "--item-id",
        default=None,
        help="対象 LearningItem。省略時は --all が必要",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="全 LearningItem を対象にする",
    )
    return parser


def _format_inconsistencies(rebuilder: ReviewScheduleRebuilder, item_id: str | None) -> int:
    found = rebuilder.detect_inconsistencies(item_id)
    if not found:
        print("inconsistencies: 0")
        return 0
    for item in found:
        print(
            f"{item.kind}\titem={item.learning_item_id}\t"
            f"direction={item.skill_direction}\t"
            f"expected_count={item.expected_review_count}\t"
            f"actual_count={item.actual_review_count}\t"
            f"expected_version={item.expected_scheduler_version}\t"
            f"actual_version={item.actual_scheduler_version}"
        )
    print(f"inconsistencies: {len(found)}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.item_id and args.all:
        build_parser().error("--item-id と --all は同時に指定できない")
    if not args.check and args.item_id is None and not args.all:
        build_parser().error("--check / --item-id / --all のいずれかを指定する")

    store = TutorSqliteStore.from_env()
    rebuilder = build_review_schedule_rebuilder(
        learning_items=store.learning_items,
        learning_events=store.learning_events,
        review_schedules=store.review_schedules,
    )
    try:
        if args.check:
            target_id = None if args.all or args.item_id is None else args.item_id
            return _format_inconsistencies(rebuilder, target_id)
        if args.all:
            rebuilt = rebuilder.rebuild_all()
            total = sum(len(schedules) for schedules in rebuilt.values())
            print(f"rebuilt items={len(rebuilt)} schedules={total}")
            return 0
        assert args.item_id is not None
        schedules = rebuilder.rebuild_for_item(args.item_id)
        print(f"rebuilt item={args.item_id} schedules={len(schedules)}")
        return 0
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

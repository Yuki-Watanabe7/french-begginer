#!/usr/bin/env python3
"""Tutor 学習品質の任意評価スクリプト（Issue #206）。

通常の pytest / CI は API key なしで通す。このスクリプトも LLM は呼ばない。
固定 clock の複数日シミュレーションと不変条件を表示する。

使い方（backend ディレクトリから）:

    uv run python ../scripts/evaluate_tutor_learning_quality.py
    uv run python ../scripts/evaluate_tutor_learning_quality.py --json
    uv run python ../scripts/evaluate_tutor_learning_quality.py --strict
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.learning_quality import (  # noqa: E402
    evaluate_all_scenarios,
    format_text_report,
    reports_failed,
    reports_to_json,
)
from app.evaluation.learning_quality_fixtures import (  # noqa: E402
    LEARNING_QUALITY_SCENARIOS,
    LearningQualityScenario,
    get_scenario,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="固定シナリオで Tutor の長期学習品質を評価する"
    )
    parser.add_argument(
        "--scenario",
        default="all",
        help="評価する scenario id。省略時はすべて",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="policy version と日次メトリクス付き JSON を出力する",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="不変条件の失敗があれば終了コード 1",
    )
    return parser


def select_scenarios(scenario_id: str) -> tuple[LearningQualityScenario, ...]:
    if scenario_id == "all":
        return LEARNING_QUALITY_SCENARIOS
    return (get_scenario(scenario_id),)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scenarios = select_scenarios(args.scenario)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reports = evaluate_all_scenarios(scenarios)
    if args.json:
        print(reports_to_json(reports))
    else:
        print(format_text_report(reports), end="")
    if args.strict and reports_failed(reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

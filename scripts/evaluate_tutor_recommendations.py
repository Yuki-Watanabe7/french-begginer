#!/usr/bin/env python3
"""Tutor 推薦品質の任意評価スクリプト（Issue #180）。

通常の pytest / CI は API key なしで通す。このスクリプトも LLM は呼ばない。
固定 fixture と反実仮想（counterfactual）の不変条件を表示する。

使い方（backend ディレクトリから）:

    uv run python ../scripts/evaluate_tutor_recommendations.py
    uv run python ../scripts/evaluate_tutor_recommendations.py --fixture A --json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.recommendation_fixtures import (  # noqa: E402
    COUNTERFACTUAL_CASES,
    RECOMMENDATION_QUALITY_FIXTURES,
    CounterfactualCase,
    LearnerScenario,
    get_fixture,
)
from app.evaluation.recommendation_quality import (  # noqa: E402
    evaluate_all_counterfactuals,
    evaluate_all_scenarios,
    format_text_report,
    reports_failed,
    reports_to_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="固定 fixture に対して Tutor 推薦品質を評価する"
    )
    parser.add_argument(
        "--fixture",
        default="all",
        help="評価する fixture id（A/B/C/D/E/F/INV）。省略時はすべて",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="feature_version / policy_version / ranked IDs 付き JSON を出力する",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="不変条件の失敗があれば終了コード 1",
    )
    parser.add_argument(
        "--no-counterfactuals",
        action="store_true",
        help="反実仮想ケースを評価しない",
    )
    return parser


def select_fixtures(fixture_id: str) -> tuple[LearnerScenario, ...]:
    if fixture_id == "all":
        return RECOMMENDATION_QUALITY_FIXTURES
    return (get_fixture(fixture_id),)


def select_counterfactuals(
    fixture_id: str,
    *,
    include: bool,
) -> tuple[CounterfactualCase, ...]:
    if not include:
        return ()
    if fixture_id == "all":
        return COUNTERFACTUAL_CASES
    if fixture_id.upper() == "A":
        return tuple(
            row
            for row in COUNTERFACTUAL_CASES
            if row.case_id == "high-interest-still-below-overdue"
        )
    return ()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixtures = select_fixtures(args.fixture)
    except KeyError:
        print(f"unknown fixture: {args.fixture}", file=sys.stderr)
        return 2
    scenarios = evaluate_all_scenarios(fixtures)
    counterfactuals = evaluate_all_counterfactuals(
        select_counterfactuals(args.fixture, include=not args.no_counterfactuals)
    )
    if args.json:
        print(reports_to_json(scenarios, counterfactuals))
    else:
        print(format_text_report(scenarios, counterfactuals), end="")
    if args.strict and reports_failed((*scenarios, *counterfactuals)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""LLM抽出品質の任意評価スクリプト（Issue #136）。

通常の pytest / CI は API key なしで通す。実 LLM 呼び出しはこのスクリプト、
または `RUN_LIVE_LLM=1 pytest -m live_llm` に分離する。

使い方（backend ディレクトリから）:

    uv run python ../scripts/evaluate_tutor_extraction.py
    uv run python ../scripts/evaluate_tutor_extraction.py --fixture A --json

LLM-as-judge は使わない。deterministic contract と fixture 期待値が根拠。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.extraction_fixtures import (  # noqa: E402
    EXTRACTION_QUALITY_FIXTURES,
    ExtractionQualityFixture,
    get_fixture,
)
from app.evaluation.extraction_quality import (  # noqa: E402
    FixtureQualityReport,
    evaluate_extraction,
    format_text_report,
    reports_to_json,
)
from app.services.exceptions import ExtractionError  # noqa: E402
from app.services.extraction_service import ExtractionService  # noqa: E402
from app.services.extractors import LearningItemExtractor  # noqa: E402
from app.services.openai_extractor import OpenAILearningItemExtractor  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="固定 fixture に対して Tutor LLM抽出の品質を評価する"
    )
    parser.add_argument(
        "--fixture",
        default="all",
        help="評価する fixture id（A/B/C/D）。省略時はすべて",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="provider / model / extraction_version 付き JSON を出力する",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI モデル名。未指定時は extractor のデフォルト",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="contract 失敗または must-have 欠落があれば終了コード 1",
    )
    return parser


def select_fixtures(fixture_id: str) -> tuple[ExtractionQualityFixture, ...]:
    if fixture_id == "all":
        return EXTRACTION_QUALITY_FIXTURES
    return (get_fixture(fixture_id.upper()),)


def evaluate_with_extractor(
    extractor: LearningItemExtractor,
    fixtures: Sequence[ExtractionQualityFixture],
) -> list[FixtureQualityReport]:
    """extractor を差し替えて評価する。テストでは fake を渡す。"""
    service = ExtractionService(extractor)
    reports: list[FixtureQualityReport] = []
    for fixture in fixtures:
        source = fixture.source_document()
        result = service.extract(source)
        reports.append(evaluate_extraction(fixture, result, source=source))
    return reports


def reports_failed_strict(reports: Sequence[FixtureQualityReport]) -> bool:
    return any(
        (not report.contract_passed) or report.missing_must_haves for report in reports
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixtures = select_fixtures(args.fixture)
    except KeyError as exc:
        print(exc.args[0] if exc.args else str(exc), file=sys.stderr)
        return 1

    extractor_kwargs: dict[str, str] = {}
    if args.model:
        extractor_kwargs["model"] = args.model
    extractor = OpenAILearningItemExtractor(**extractor_kwargs)

    try:
        reports = evaluate_with_extractor(extractor, fixtures)
    except ExtractionError as exc:
        print(f"抽出に失敗しました: {exc}", file=sys.stderr)
        if not os.environ.get("OPENAI_API_KEY"):
            print(
                "OPENAI_API_KEY が未設定です。"
                "通常の pytest は key なしで通します。"
                "実 LLM 評価だけが key を必要とします。",
                file=sys.stderr,
            )
        return 1

    if args.json:
        print(reports_to_json(reports))
    else:
        print(format_text_report(reports), end="")

    if args.strict and reports_failed_strict(reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

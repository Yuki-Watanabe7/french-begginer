"""複数 LearningItem 横断の苦手パターン（Issue #203）。

metadata に書いてある tag だけを集計する。1 Item や attempt 不足、
直近窓の外の誤答では苦手と断定しない。recognition と production は分ける。
"""

from __future__ import annotations

import ast
import inspect
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.recommendation_ranking import COMPONENT_NAMES, COMPONENT_WEIGHTS
from app.domain.recommendation_signal import extract_recommendation_signal
from app.domain.today_session import explain_reason_codes
from app.domain.tutor import LearningEvent, LearningItem
from app.domain.weakness_pattern import (
    ERROR_RATE_THRESHOLD,
    MIN_ATTEMPTS,
    MIN_DISTINCT_ITEMS,
    MIN_RECENT_INCORRECT,
    PATTERN_VERSION,
    RECENT_WINDOW_DAYS,
    aggregate_weakness_patterns,
    extract_pattern_tags,
    pattern_reason_notes,
    weakness_hints_for_item,
)
from app.evaluation.weakness_pattern_quality import evaluate_weakness_pattern_quality
from app.repositories.sqlite import TutorSqliteStore
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service
from app.services.weakness_pattern_service import build_weakness_pattern_service

_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _item(
    item_id: str,
    *,
    item_type: str = "expression",
    form: str | None = None,
    metadata: dict | None = None,
) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type=item_type,  # type: ignore[arg-type]
        canonical_form=item_id if form is None else form,
        meaning_ja="意味",
        metadata=metadata or {},
        created_at=_NOW - timedelta(days=40),
    )


def _events(
    item_id: str,
    *,
    count: int,
    result: str = "incorrect",
    exercise_type: str = "ja_to_fr",
    days_ago: float = 1,
    prefix: str = "",
) -> list[LearningEvent]:
    outcome = "incorrect" if result == "incorrect" else "correct"
    return [
        LearningEvent(
            id=f"{prefix}{item_id}-{index}",
            learning_item_id=item_id,
            exercise_type=exercise_type,  # type: ignore[arg-type]
            result=outcome,
            occurred_at=_NOW - timedelta(days=days_ago, hours=index),
        )
        for index in range(count)
    ]


def _report(items: list[LearningItem], events: list[LearningEvent]):
    return aggregate_weakness_patterns(items, events, now=_NOW)


def test_shared_pattern_across_items_is_detected() -> None:
    items = [
        _item(
            "se-lever",
            item_type="expression",
            form="se lever",
            metadata={"pronominal": True},
        ),
        _item(
            "se-laver",
            item_type="vocabulary",
            form="se laver",
            metadata={"pronominal": True},
        ),
    ]
    events = _events("se-lever", count=MIN_ATTEMPTS) + _events(
        "se-laver", count=MIN_ATTEMPTS
    )
    report = _report(items, events)
    pattern = next(
        row for row in report.weaknesses if row.pattern_key == "pronominal:true"
    )
    assert pattern.label == "代名動詞"
    assert pattern.version == PATTERN_VERSION
    assert pattern.computed_at == _NOW
    assert pattern.evidence_item_ids == ("se-laver", "se-lever")
    assert pattern.affected_item_count == 2
    assert pattern.by_direction["production"].is_weakness is True
    assert pattern.by_direction["production"].error_rate == 1.0
    notes = pattern_reason_notes(weakness_hints_for_item("se-lever", report))
    assert (
        notes["PRODUCTION_PATTERN_WEAKNESS"]
        == "最近、代名動詞の自力回答で間違いが続いています"
    )


def test_single_item_is_not_called_a_weakness() -> None:
    items = [_item("only", metadata={"verb_group": "irregular"})]
    events = _events("only", count=MIN_ATTEMPTS + 4)
    report = _report(items, events)
    assert report.weaknesses == ()
    assert any(row.pattern_key == "verb_group:irregular" for row in report.patterns)
    assert all(row.affected_item_count == 1 for row in report.patterns)


def test_too_few_attempts_are_not_a_weakness() -> None:
    items = [
        _item("a", metadata={"tense": "imparfait"}),
        _item("b", metadata={"tense": "imparfait"}),
    ]
    events = _events("a", count=1) + _events("b", count=1)
    report = _report(items, events)
    pattern = next(
        row for row in report.patterns if row.pattern_key == "tense:imparfait"
    )
    assert pattern.is_weakness is False
    assert pattern.label == "半過去"
    stats = pattern.by_direction["production"]
    assert stats.recent_affected_item_count >= MIN_DISTINCT_ITEMS
    assert stats.recent_attempt_count < MIN_ATTEMPTS
    assert stats.recent_incorrect_count >= MIN_RECENT_INCORRECT


def test_recognition_and_production_are_separate() -> None:
    items = [
        _item(
            "g1",
            item_type="vocabulary",
            metadata={"grammar_feature": "noun_with_article"},
        ),
        _item(
            "g2",
            item_type="expression",
            metadata={"grammar_feature": "noun_with_article"},
        ),
    ]
    events = (
        _events("g1", count=MIN_ATTEMPTS, exercise_type="ja_to_fr")
        + _events("g2", count=MIN_ATTEMPTS, exercise_type="ja_to_fr")
        + _events(
            "g1",
            count=MIN_ATTEMPTS,
            result="correct",
            exercise_type="meaning_recognition",
            prefix="rec-",
        )
        + _events(
            "g2",
            count=MIN_ATTEMPTS,
            result="correct",
            exercise_type="meaning_recognition",
            prefix="rec-",
        )
    )
    report = _report(items, events)
    pattern = next(
        row
        for row in report.patterns
        if row.pattern_key == "grammar_feature:noun_with_article"
    )
    assert pattern.label == "冠詞付き名詞"
    assert pattern.weak_directions == ("production",)
    assert pattern.by_direction["recognition"].is_weakness is False
    assert pattern.by_direction["recognition"].recent_error_rate == 0.0
    assert pattern.by_direction["production"].evidence_item_ids == ("g1", "g2")
    hints = weakness_hints_for_item("g1", report)
    assert [hint.skill_direction for hint in hints] == ["production"]


def test_old_errors_outside_the_window_do_not_define_a_weakness() -> None:
    items = [
        _item("old-a", metadata={"mood": "subjonctif"}),
        _item("old-b", metadata={"mood": "subjonctif"}),
    ]
    old = _events(
        "old-a",
        count=MIN_ATTEMPTS,
        days_ago=RECENT_WINDOW_DAYS + 3,
    ) + _events(
        "old-b",
        count=MIN_ATTEMPTS,
        days_ago=RECENT_WINDOW_DAYS + 3,
    )
    recent = _events(
        "old-a",
        count=MIN_ATTEMPTS,
        result="correct",
        days_ago=1,
        prefix="recent-",
    ) + _events(
        "old-b",
        count=MIN_ATTEMPTS,
        result="correct",
        days_ago=1,
        prefix="recent-",
    )
    report = _report(items, old + recent)
    pattern = next(
        row for row in report.patterns if row.pattern_key == "mood:subjonctif"
    )
    assert pattern.error_rate >= ERROR_RATE_THRESHOLD
    assert pattern.recent_error_count == 0
    assert pattern.is_weakness is False
    assert pattern.by_direction["production"].recent_error_rate == 0.0


def test_missing_metadata_is_not_inferred() -> None:
    items = [
        _item("se-laver", form="se laver"),
        _item("parler", form="parler", item_type="conjugation"),
        _item("maison", form="maison", item_type="vocabulary"),
    ]
    events = []
    for item in items:
        events.extend(_events(item.id, count=MIN_ATTEMPTS))
    report = _report(items, events)
    keys = {row.pattern_key for row in report.patterns}
    assert "pronominal:true" not in keys
    assert "verb_group:er" not in keys
    assert "noun_gender:feminine" not in keys
    assert "tense:présent" not in keys
    for item in items:
        dimensions = {tag.dimension for tag in extract_pattern_tags(item)}
        assert dimensions == {"item_type"}


def test_explicit_tags_cover_the_taxonomy() -> None:
    item = _item(
        "aller",
        item_type="conjugation",
        form="aller",
        metadata={
            "verb_group": "-ER",
            "tense": "Présent",
            "mood": "indicatif",
            "gender": "masculine",
            "noun_gender": "feminine",
            "tags": [
                "grammar_feature:il_faut",
                "pronominal:true",
                "unknown:guess",
                "item_type:vocabulary",
            ],
        },
    )
    keys = {tag.pattern_key: tag.label for tag in extract_pattern_tags(item)}
    assert keys["item_type:conjugation"] == "動詞活用"
    assert keys["verb_group:er"] == "-er 動詞"
    assert keys["tense:présent"] == "現在形"
    assert keys["mood:indicatif"] == "直説法"
    assert keys["grammar_feature:il_faut"] == "il faut 系"
    assert keys["pronominal:true"] == "代名動詞"
    assert "noun_gender:masculine" not in keys
    assert "noun_gender:feminine" not in keys
    assert "unknown:guess" not in keys
    assert "item_type:vocabulary" not in keys


def test_aggregation_is_deterministic() -> None:
    items = [
        _item("b", metadata={"verb_group": "ir"}),
        _item("a", metadata={"verb_group": "ir"}),
    ]
    events = _events("a", count=MIN_ATTEMPTS, prefix="a-") + _events(
        "b", count=MIN_ATTEMPTS, prefix="b-"
    )
    shuffled_items = list(items)
    shuffled_events = list(events)
    random.Random(203).shuffle(shuffled_items)
    random.Random(203).shuffle(shuffled_events)
    assert _report(items, events) == _report(shuffled_items, shuffled_events)


def test_pattern_component_is_zero_without_hints() -> None:
    item = _item("plain")
    snapshot = extract_recommendation_signal(item, now=_NOW)
    assert snapshot.weakness_patterns == ()
    from app.domain.recommendation_ranking import score_recommendation

    score = score_recommendation(snapshot, "recognition", "new_practice")
    assert score.components["pattern_weakness"] == 0.0
    assert "PATTERN_RECENT_ERRORS" not in score.reason_codes
    assert "PRODUCTION_PATTERN_WEAKNESS" not in score.reason_codes
    assert set(score.components) == set(COMPONENT_NAMES)
    soft = (
        COMPONENT_WEIGHTS["level_fit"]
        + COMPONENT_WEIGHTS["source_recency"]
        + COMPONENT_WEIGHTS["interest"]
        + COMPONENT_WEIGHTS["importance"]
        + COMPONENT_WEIGHTS["pattern_weakness"]
    )
    assert soft < COMPONENT_WEIGHTS["overdue"] * 0.8


def test_quality_fixtures_pass() -> None:
    checks = evaluate_weakness_pattern_quality()
    failed = [row for row in checks if not row.passed]
    assert failed == []
    assert {row.name for row in checks} >= {
        "shared_pronominal_production",
        "single_item_is_not_a_pattern",
        "missing_metadata_is_not_inferred",
        "pattern_weight_does_not_beat_due",
        "production_pattern_reason",
    }


def test_today_plan_uses_pattern_reason_without_burying_due() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    today = build_today_learning_service(store, clock=lambda: _NOW)
    lever = tutor.create_item(
        item_type="expression",
        canonical_form="se lever",
        meaning_ja="起きる",
        metadata={"pronominal": True},
    )
    laver = tutor.create_item(
        item_type="vocabulary",
        canonical_form="se laver",
        meaning_ja="洗う",
        metadata={"pronominal": True},
    )
    fresh = tutor.create_item(
        item_type="vocabulary",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        metadata={"interest_weight": 3.0, "importance_weight": 3.0},
    )
    for item in (lever, laver):
        for attempt in range(MIN_ATTEMPTS):
            tutor.record_review(
                item.id,
                exercise_type="ja_to_fr",
                result="incorrect",
                occurred_at=_NOW - timedelta(days=2, hours=attempt),
            )
    plan = today.get_plan(question_count=10, max_new_count=3)
    reviews = [row for row in plan.entries if row.activity_kind == "review"]
    news = [row for row in plan.entries if row.activity_kind == "new_practice"]
    assert reviews
    assert all(row.learning_item_id != fresh.id for row in reviews)
    assert news[0].learning_item_id == fresh.id
    assert plan.entries[0].activity_kind == "review"
    production = [
        row
        for row in reviews
        if row.skill_direction == "production" and row.learning_item_id == lever.id
    ]
    assert production
    assert "PRODUCTION_PATTERN_WEAKNESS" in production[0].reason_codes
    assert "最近、代名動詞の自力回答で間違いが続いています" in production[0].explanation
    generic = explain_reason_codes(("PRODUCTION_PATTERN_WEAKNESS",))
    assert generic in production[0].explanation
    assert "PATTERN_RECENT_ERRORS" not in production[0].reason_codes


def test_patterns_recompute_the_same_after_db_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "weakness.db"
    url = f"sqlite:///{db_path}"
    store = TutorSqliteStore(url)
    tutor = build_tutor_service(store, clock=lambda: _NOW)
    service = build_weakness_pattern_service(store, clock=lambda: _NOW)
    for form in ("finir", "choisir"):
        item = tutor.create_item(
            item_type="conjugation",
            canonical_form=form,
            meaning_ja=form,
            metadata={"verb_group": "ir", "tense": "imparfait"},
        )
        for attempt in range(MIN_ATTEMPTS):
            tutor.record_review(
                item.id,
                exercise_type="cloze",
                result="incorrect",
                occurred_at=_NOW - timedelta(days=1, hours=attempt),
            )
    first = service.detect(now=_NOW)
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    again = build_weakness_pattern_service(reopened, clock=lambda: _NOW).detect(
        now=_NOW
    )
    assert again == first
    tense = next(
        row for row in again.weaknesses if row.pattern_key == "tense:imparfait"
    )
    group = next(row for row in again.weaknesses if row.pattern_key == "verb_group:ir")
    assert tense.label == "半過去"
    assert group.label == "-ir 動詞"
    assert tense.evidence_item_ids == group.evidence_item_ids
    assert len(tense.evidence_item_ids) == MIN_DISTINCT_ITEMS
    reopened.engine.dispose()


def test_modules_do_not_import_llm_or_fastapi() -> None:
    import app.domain.weakness_pattern as pattern_module
    import app.services.weakness_pattern_service as service_module

    forbidden = {"openai", "fastapi", "app.api", "app.persistence"}
    for module in (pattern_module, service_module):
        names: set[str] = set()
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
                names.add(node.module)
        assert not (names & forbidden)

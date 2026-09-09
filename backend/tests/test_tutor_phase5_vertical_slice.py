"""Signal → Ranking → 今日の学習 → 履歴更新の vertical slice。

Issue #181 / Phase 5。学習履歴・弱点・Source・レベルから今日の学習枠を
構成し、理由付きで解き、回答後の再 plan が最新状態を反映することを
HTTP API + SQLite で一本につなぐ。実時間待ちと実 LLM は使わない。
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    get_today_learning_service,
    get_tutor_service,
    get_tutor_store,
)
from app.domain.daily_learning_plan import POLICY_VERSION as PLAN_POLICY_VERSION
from app.domain.exercise import tokenize_canonical_form
from app.domain.exercise_generation import DEFAULT_GENERATION_SEED, generate_exercise
from app.domain.noun import NOUNS
from app.domain.recommendation_ranking import (
    COMPONENT_NAMES,
    rank_recommendations,
)
from app.domain.recommendation_ranking import (
    POLICY_VERSION as RANKING_POLICY_VERSION,
)
from app.domain.recommendation_signal import (
    FEATURE_VERSION,
    SKILL_DIRECTIONS,
    extract_recommendation_signal,
)
from app.domain.today_session import REASON_EXPLANATIONS
from app.domain.tutor import SourceDocument
from app.main import app
from app.persistence.models import LearningItemRow, ReviewScheduleRow
from app.repositories.sqlite import TutorSqliteStore
from app.services.today_learning_service import build_today_learning_service
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
RECENT_SOURCE_AT = NOW - timedelta(days=1)
OLD_SOURCE_AT = NOW - timedelta(days=40)

_LEAKED_ANSWER_KEYS = {
    "expected",
    "expected_answer",
    "expected_answers",
    "answer",
    "answer_key",
    "correct",
    "correct_answer",
    "correct_option",
    "correct_index",
    "correct_option_index",
    "metadata",
    "rank_score",
    "total_score",
    "components",
}


@dataclass
class FrozenClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def _bind(store: TutorSqliteStore, clock: FrozenClock) -> None:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_tutor_service] = lambda: build_tutor_service(
        store, clock=clock
    )
    app.dependency_overrides[get_today_learning_service] = lambda: (
        build_today_learning_service(store, clock=clock)
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def store() -> TutorSqliteStore:
    return TutorSqliteStore.in_memory()


@pytest.fixture
def client(store: TutorSqliteStore, clock: FrozenClock) -> Iterator[TestClient]:
    _bind(store, clock)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_source(
    store: TutorSqliteStore,
    *,
    title: str,
    content: str,
    created_at: datetime,
) -> SourceDocument:
    document = SourceDocument(
        title=title,
        content=content,
        created_at=created_at,
        metadata={"note": title},
    )
    return store.source_documents.create(document)


def _create_item(client: TestClient, **overrides) -> dict:
    payload = {
        "item_type": "vocabulary",
        "canonical_form": "livre",
        "meaning_ja": "本",
    }
    payload.update(overrides)
    res = client.post("/api/tutor/items", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["item"]


def _record_review(
    client: TestClient,
    item_id: str,
    *,
    exercise_type: str,
    result: str,
    occurred_at: datetime,
    event_id: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "exercise_type": exercise_type,
        "result": result,
        "occurred_at": occurred_at.isoformat(),
    }
    if event_id is not None:
        payload["id"] = event_id
    res = client.post(f"/api/tutor/items/{item_id}/reviews", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _generated(store: TutorSqliteStore, item_id: str, exercise_type: str):
    item = store.learning_items.get(item_id)
    assert item is not None
    sources = {}
    for ref in item.source_refs:
        document = store.source_documents.get(ref.source_document_id)
        if document is not None:
            sources[document.id] = document
    result = generate_exercise(
        item,
        exercise_type,
        pool=store.learning_items.list(),
        seed=DEFAULT_GENERATION_SEED,
        sources=sources,
    )
    assert result.exercise is not None, result.skip_reason
    return result.exercise


def _answer(
    client: TestClient,
    store: TutorSqliteStore,
    item_id: str,
    exercise_type: str,
    *,
    correct: bool = True,
    event_id: str | None = None,
) -> dict:
    generated = _generated(store, item_id, exercise_type)
    expected = generated.answer_key.expected_answers[0]
    if correct:
        if generated.spec.response_kind == "reconstruction":
            payload_answer: str | list[str] = list(tokenize_canonical_form(expected))
        else:
            payload_answer = expected
    else:
        payload_answer = "wrong-answer"
    payload: dict[str, object] = {"answer": payload_answer}
    if event_id is not None:
        payload["id"] = event_id
    res = client.post(
        f"/api/tutor/items/{item_id}/exercises/{exercise_type}/answer",
        json=payload,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _today_plan(
    client: TestClient,
    *,
    question_count: int = 10,
    max_new_count: int = 3,
) -> dict:
    res = client.get(
        "/api/tutor/today",
        params={"question_count": question_count, "max_new_count": max_new_count},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _today_session(
    client: TestClient,
    *,
    question_count: int = 10,
    max_new_count: int = 3,
    seed: str = "phase5",
) -> dict:
    res = client.post(
        "/api/tutor/today/sessions",
        json={
            "question_count": question_count,
            "max_new_count": max_new_count,
            "seed": seed,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _item_detail(client: TestClient, item_id: str) -> dict:
    res = client.get(f"/api/tutor/items/{item_id}")
    assert res.status_code == 200, res.text
    return res.json()


def _schedules_by_direction(detail: dict) -> dict[str, dict]:
    return {row["skill_direction"]: row for row in detail["review_schedules"]}


def _assert_no_answer_leak(body: dict) -> None:
    assert _LEAKED_ANSWER_KEYS.isdisjoint(body)


def _snapshots(store: TutorSqliteStore, now: datetime):
    sources = {row.id: row for row in store.source_documents.list()}
    snapshots = []
    for item in store.learning_items.list():
        if item.status != "active":
            continue
        snapshots.append(
            extract_recommendation_signal(
                item,
                learner_state=store.learner_states.get(item.id),
                schedules_by_direction={
                    row.skill_direction: row
                    for row in store.review_schedules.list_for_item(item.id)
                },
                events_by_direction={
                    direction: store.learning_events.list_by_item_and_direction(
                        item.id, direction
                    )
                    for direction in SKILL_DIRECTIONS
                },
                sources_by_id=sources,
                now=now,
            )
        )
    return snapshots


def _ranked(store: TutorSqliteStore, now: datetime):
    return rank_recommendations(_snapshots(store, now))


def _entry_by_form(plan: dict, canonical_form: str) -> dict:
    matches = [
        row for row in plan["entries"] if row["canonical_form"] == canonical_form
    ]
    assert matches, canonical_form
    return matches[0]


def _seed_recommended_fixture(
    client: TestClient, store: TutorSqliteStore
) -> dict[str, dict]:
    """Issue #181 推奨 fixture。A〜E の役割を固定する。"""
    recent = _create_source(
        store,
        title="Recent article",
        content="Je me suis rendu compte qu'il fallait changer de stratégie.",
        created_at=RECENT_SOURCE_AT,
    )
    old = _create_source(
        store,
        title="Old article",
        content="Hier, l'ancien bâtiment était fermé.",
        created_at=OLD_SOURCE_AT,
    )
    item_a = _create_item(
        client,
        item_type="expression",
        canonical_form="se rendre compte de",
        meaning_ja="〜に気づく",
        explanation_ja="よく出る表現",
        level="A2",
        source_refs=[{"source_document_id": recent.id}],
    )
    item_b = _create_item(
        client,
        canonical_form="stratégie",
        meaning_ja="戦略",
        level="A2",
        source_refs=[{"source_document_id": recent.id}],
    )
    item_c = _create_item(
        client,
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        level="B1",
        source_refs=[{"source_document_id": recent.id}],
        metadata={"interest_weight": 2.0},
    )
    item_d = _create_item(
        client,
        canonical_form="ancien",
        meaning_ja="古い",
        level="B1",
        source_refs=[{"source_document_id": old.id}],
        metadata={"interest_weight": 1.0},
    )
    item_e = _create_item(
        client,
        canonical_form="mystère",
        meaning_ja="謎",
    )

    _record_review(
        client,
        item_a["id"],
        exercise_type="meaning_recognition",
        result="correct",
        occurred_at=NOW - timedelta(hours=12),
        event_id="evt-a-rec-1",
    )
    _record_review(
        client,
        item_a["id"],
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=15),
        event_id="evt-a-prod-1",
    )
    _record_review(
        client,
        item_a["id"],
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW - timedelta(days=8),
        event_id="evt-a-prod-2",
    )

    for offset, event_id in (
        (30, "evt-b-rec-1"),
        (20, "evt-b-rec-2"),
        (10, "evt-b-rec-3"),
        (3, "evt-b-rec-4"),
    ):
        _record_review(
            client,
            item_b["id"],
            exercise_type="meaning_recognition",
            result="correct",
            occurred_at=NOW - timedelta(days=offset),
            event_id=event_id,
        )
    for offset, event_id in (
        (20, "evt-b-prod-1"),
        (12, "evt-b-prod-2"),
        (6, "evt-b-prod-3"),
        (1, "evt-b-prod-4"),
    ):
        _record_review(
            client,
            item_b["id"],
            exercise_type="ja_to_fr",
            result="incorrect" if offset == 1 else "correct",
            occurred_at=NOW - timedelta(days=offset),
            event_id=event_id,
        )

    return {
        "A": item_a,
        "B": item_b,
        "C": item_c,
        "D": item_d,
        "E": item_e,
        "recent_source": {"id": recent.id, "title": recent.title},
        "old_source": {"id": old.id, "title": old.title},
    }


def _create_due_vocab(
    client: TestClient,
    *,
    form: str,
    meaning: str,
    direction: str = "recognition",
    occurred_at: datetime | None = None,
) -> dict:
    item = _create_item(client, canonical_form=form, meaning_ja=meaning)
    due_at = occurred_at or (NOW - timedelta(days=2))
    if direction == "recognition":
        _record_review(
            client,
            item["id"],
            exercise_type="meaning_recognition",
            result="incorrect",
            occurred_at=due_at,
        )
        _record_review(
            client,
            item["id"],
            exercise_type="ja_to_fr",
            result="correct",
            occurred_at=NOW - timedelta(hours=12),
        )
    else:
        _record_review(
            client,
            item["id"],
            exercise_type="ja_to_fr",
            result="incorrect",
            occurred_at=due_at,
        )
        _record_review(
            client,
            item["id"],
            exercise_type="meaning_recognition",
            result="correct",
            occurred_at=NOW - timedelta(hours=12),
        )
    return item


def _set_item_status(store: TutorSqliteStore, item_id: str, status: str) -> None:
    item = store.learning_items.get(item_id)
    assert item is not None
    updated = item.model_copy(update={"status": status})
    with Session(store.engine) as session:
        session.merge(LearningItemRow.from_domain(updated))
        session.commit()


def test_phase5_signal_to_today_to_replan_vertical_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """必須 vertical slice: 履歴 → signal → ranking → Plan → Session → 再plan → 再open。

    推奨 fixture A〜E を使い、due review が新規より先、C が D より先、
    unknown level が排除されず、回答後の次 Plan が最新状態を反映することを
    確認する。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db_path = tmp_path / "tutor-phase5.db"
    file_store = TutorSqliteStore(f"sqlite:///{db_path}")
    file_clock = FrozenClock(NOW)
    _bind(file_store, file_clock)
    try:
        with TestClient(app) as http:
            items = _seed_recommended_fixture(http, file_store)
            item_a = items["A"]
            item_b = items["B"]
            item_c = items["C"]
            item_d = items["D"]
            item_e = items["E"]

            snapshots = {
                snap.learning_item_id: snap for snap in _snapshots(file_store, NOW)
            }
            snap_a = snapshots[item_a["id"]]
            snap_b = snapshots[item_b["id"]]
            snap_c = snapshots[item_c["id"]]
            snap_e = snapshots[item_e["id"]]
            assert snap_a.feature_version == FEATURE_VERSION
            assert snap_a.by_direction["production"].review_urgency == "due"
            assert snap_a.by_direction["production"].overdue_days > 0
            assert 0.4 <= snap_a.by_direction["production"].mastery_score <= 0.6
            assert snap_b.by_direction["recognition"].mastery_score == 1.0
            assert snap_b.by_direction["production"].mastery_score == 0.75
            assert snap_b.production_gap == 0.25
            assert snap_b.by_direction["production"].recent_incorrect_count >= 1
            assert snap_c.by_direction["recognition"].is_unseen is True
            assert snap_c.source_recency_days is not None
            assert snap_c.source_recency_days < 2
            assert snap_e.item_level is None
            assert snap_e.level_distance is None

            ranked = _ranked(file_store, NOW)
            ranked_keys = [
                (row.learning_item_id, row.skill_direction, row.activity_kind)
                for row in ranked
            ]
            assert ranked_keys[0] == (item_a["id"], "production", "review")
            assert ranked_keys[1] == (item_b["id"], "production", "review")
            new_ids = []
            for row in ranked:
                if (
                    row.activity_kind == "new_practice"
                    and row.learning_item_id not in new_ids
                ):
                    new_ids.append(row.learning_item_id)
            assert new_ids[:3] == [item_c["id"], item_d["id"], item_e["id"]]
            assert (item_c["id"], "recognition", "new_practice") in ranked_keys
            score_a = next(
                row.score
                for row in ranked
                if ranked_keys[0]
                == (
                    row.learning_item_id,
                    row.skill_direction,
                    row.activity_kind,
                )
            )
            assert set(score_a.components) == set(COMPONENT_NAMES)
            assert score_a.policy_version == RANKING_POLICY_VERSION
            assert abs(sum(score_a.components.values()) - score_a.total_score) < 1e-9
            assert "OVERDUE_REVIEW" in score_a.reason_codes
            score_b = next(
                row.score
                for row in ranked
                if row.learning_item_id == item_b["id"]
                and row.activity_kind == "review"
            )
            assert "PRODUCTION_WEAKER" in score_b.reason_codes
            assert "RECENT_ERROR" in score_b.reason_codes
            rec_b = snap_b.by_direction["recognition"]
            assert rec_b.recent_incorrect_count == 0
            prod_b_units = [
                row
                for row in ranked
                if row.learning_item_id == item_b["id"]
                and row.skill_direction == "recognition"
            ]
            assert all(row.activity_kind != "review" for row in prod_b_units)
            score_c = next(
                row.score
                for row in ranked
                if row.learning_item_id == item_c["id"]
                and row.activity_kind == "new_practice"
            )
            assert "LOW_MASTERY" not in score_c.reason_codes
            assert "RECENT_SOURCE" in score_c.reason_codes
            score_d = next(
                row.score for row in ranked if row.learning_item_id == item_d["id"]
            )
            assert "HIGH_INTEREST" not in score_d.reason_codes
            score_e = next(
                row.score for row in ranked if row.learning_item_id == item_e["id"]
            )
            assert "LEVEL_FIT" not in score_e.reason_codes

            plan = _today_plan(http)
            assert plan["policy_version"] == PLAN_POLICY_VERSION
            assert plan["review_count"] == 2
            assert plan["new_count"] == 3
            assert plan["total_count"] == 5
            assert plan["deferred_due_count"] == 0
            assert plan["generated_at"].startswith("2026-09-09T12:00:00")
            for entry in plan["entries"]:
                _assert_no_answer_leak(entry)
            forms = [row["canonical_form"] for row in plan["entries"]]
            assert forms[:2] == ["se rendre compte de", "stratégie"]
            assert plan["entries"][0]["activity_kind"] == "review"
            assert plan["entries"][0]["skill_direction"] == "production"
            assert plan["entries"][1]["activity_kind"] == "review"
            assert plan["entries"][1]["skill_direction"] == "production"
            assert [row["canonical_form"] for row in plan["entries"][2:]] == [
                "bonjour",
                "ancien",
                "mystère",
            ]
            assert all(
                row["activity_kind"] == "new_practice"
                and row["skill_direction"] == "recognition"
                for row in plan["entries"][2:]
            )
            overdue = _entry_by_form(plan, "se rendre compte de")
            assert "OVERDUE_REVIEW" in overdue["reason_codes"]
            assert REASON_EXPLANATIONS["OVERDUE_REVIEW"] in overdue["explanation"]
            weaker = _entry_by_form(plan, "stratégie")
            assert "PRODUCTION_WEAKER" in weaker["reason_codes"]
            assert REASON_EXPLANATIONS["PRODUCTION_WEAKER"] in weaker["explanation"]
            recent_new = _entry_by_form(plan, "bonjour")
            assert "RECENT_SOURCE" in recent_new["reason_codes"]
            assert items["recent_source"]["title"] in recent_new["source_titles"]
            unknown = _entry_by_form(plan, "mystère")
            assert "LEVEL_FIT" not in unknown["reason_codes"]
            assert "HIGH_INTEREST" not in unknown["explanation"]
            again = _today_plan(http)
            assert [row["learning_item_id"] for row in again["entries"]] == [
                row["learning_item_id"] for row in plan["entries"]
            ]

            session = _today_session(http)
            assert session["generated_count"] == 5
            assert session["review_count"] == 2
            assert session["new_count"] == 3
            assert session["skipped_entries"] == []
            exercises = session["exercises"]
            entries = session["entries"]
            for row in exercises:
                _assert_no_answer_leak(row)
                assert "correct_answer" not in row
            assert [row["learning_item_id"] for row in exercises] == [
                row["learning_item_id"] for row in entries
            ]
            assert exercises[0]["skill_direction"] == "production"
            assert exercises[0]["learning_item_id"] == item_a["id"]
            assert exercises[1]["skill_direction"] == "production"
            assert exercises[2]["skill_direction"] == "recognition"
            assert exercises[2]["learning_item_id"] == item_c["id"]
            before_c = _item_detail(http, item_c["id"])
            assert before_c["review_schedules"] == []
            assert before_c["learner_state"] is None

            review_answer = _answer(
                http,
                file_store,
                item_a["id"],
                exercises[0]["exercise_type"],
                event_id="evt-today-review-a",
            )
            assert review_answer["correct"] is True
            assert review_answer["event"]["metadata"]["skill_direction"] == "production"
            assert review_answer["review_schedule"]["skill_direction"] == "production"
            assert review_answer["review_schedule"]["interval_days"] == 3.0
            assert review_answer["review_schedule"]["due_at"] > plan["generated_at"]
            new_answer = _answer(
                http,
                file_store,
                item_c["id"],
                exercises[2]["exercise_type"],
                event_id="evt-today-new-c",
            )
            assert new_answer["correct"] is True
            assert new_answer["event"]["metadata"]["skill_direction"] == "recognition"
            assert new_answer["review_schedule"]["skill_direction"] == "recognition"
            after_c = _schedules_by_direction(_item_detail(http, item_c["id"]))
            assert "recognition" in after_c
            assert "production" not in after_c

            next_plan = _today_plan(http)
            next_ids = {row["learning_item_id"] for row in next_plan["entries"]}
            assert not any(
                row["learning_item_id"] == item_a["id"]
                and row["activity_kind"] == "review"
                for row in next_plan["entries"]
            )
            assert not any(
                row["learning_item_id"] == item_c["id"]
                and row["activity_kind"] == "new_practice"
                and row["skill_direction"] == "recognition"
                for row in next_plan["entries"]
            )
            assert item_b["id"] in next_ids
            assert item_d["id"] in next_ids
            assert item_e["id"] in next_ids
            remaining_review = [
                row for row in next_plan["entries"] if row["activity_kind"] == "review"
            ]
            assert remaining_review[0]["learning_item_id"] == item_b["id"]
            assert remaining_review[0]["skill_direction"] == "production"
            persisted_keys = [
                (row.learning_item_id, row.skill_direction, row.activity_kind)
                for row in _ranked(file_store, NOW)
            ]
    finally:
        app.dependency_overrides.clear()
        file_store.engine.dispose()

    reopened = TutorSqliteStore(f"sqlite:///{db_path}")
    reopen_clock = FrozenClock(NOW)
    _bind(reopened, reopen_clock)
    try:
        with TestClient(app) as http:
            loaded_a = _item_detail(http, item_a["id"])
            loaded_c = _item_detail(http, item_c["id"])
            assert (
                loaded_a["learner_state"]["by_direction"]["production"]["correct_count"]
                >= 2
            )
            assert "recognition" in _schedules_by_direction(loaded_c)
            events_a = {
                event.id: event
                for event in reopened.learning_events.list_by_item(item_a["id"])
            }
            events_c = {
                event.id: event
                for event in reopened.learning_events.list_by_item(item_c["id"])
            }
            assert "evt-today-review-a" in events_a
            assert "evt-today-new-c" in events_c
            reopened_keys = [
                (row.learning_item_id, row.skill_direction, row.activity_kind)
                for row in _ranked(reopened, NOW)
            ]
            assert reopened_keys == persisted_keys
            replan = _today_plan(http)
            assert not any(
                row["learning_item_id"] == item_a["id"]
                and row["activity_kind"] == "review"
                for row in replan["entries"]
            )
            assert item_b["id"] in {
                row["learning_item_id"] for row in replan["entries"]
            }
    finally:
        app.dependency_overrides.clear()
        reopened.engine.dispose()


def test_phase5_ranking_explanations_match_signals_and_stay_deterministic(
    client: TestClient, store: TutorSqliteStore
):
    items = _seed_recommended_fixture(client, store)
    first = _ranked(store, NOW)
    second = _ranked(store, NOW)
    assert [
        (
            row.learning_item_id,
            row.skill_direction,
            row.activity_kind,
            row.score.total_score,
        )
        for row in first
    ] == [
        (
            row.learning_item_id,
            row.skill_direction,
            row.activity_kind,
            row.score.total_score,
        )
        for row in second
    ]
    plan = _today_plan(client)
    by_id = {row["learning_item_id"]: row for row in plan["entries"]}
    for ranked in first:
        public = by_id.get(ranked.learning_item_id)
        if public is None:
            continue
        if (
            public["skill_direction"] != ranked.skill_direction
            or public["activity_kind"] != ranked.activity_kind
        ):
            continue
        for code in public["reason_codes"]:
            assert code in ranked.score.reason_codes
            assert REASON_EXPLANATIONS[code] in public["explanation"]

    unseen = next(
        row
        for row in first
        if (
            row.learning_item_id == items["C"]["id"]
            and row.activity_kind == "new_practice"
        )
    )
    assert unseen.score.components["low_mastery"] == 0.0
    unknown = next(row for row in first if row.learning_item_id == items["E"]["id"])
    assert "LEVEL_FIT" not in unknown.score.reason_codes
    old_new = next(row for row in first if row.learning_item_id == items["D"]["id"])
    assert "HIGH_INTEREST" not in old_new.score.reason_codes
    due_ids = {row.learning_item_id for row in first if row.activity_kind == "review"}
    new_before_due = [
        row
        for row in first
        if row.activity_kind == "new_practice" and row.learning_item_id in due_ids
    ]
    assert new_before_due == []
    first_new_index = next(
        index for index, row in enumerate(first) if row.activity_kind == "new_practice"
    )
    assert all(row.activity_kind == "review" for row in first[:first_new_index])


def test_phase5_new_review_mix_under_and_over_capacity(
    client: TestClient, store: TutorSqliteStore
):
    due_under = [
        _create_due_vocab(
            client,
            form=f"due-under-{index}",
            meaning=f"期限下{index}",
            occurred_at=NOW - timedelta(days=3 - (index * 0.1)),
        )
        for index in range(4)
    ]
    news = [
        _create_item(
            client,
            canonical_form=f"new-under-{index}",
            meaning_ja=f"新規下{index}",
        )
        for index in range(5)
    ]
    under = _today_plan(client, question_count=10, max_new_count=3)
    assert under["review_count"] == 4
    assert under["new_count"] == 3
    assert under["total_count"] == 7
    assert under["deferred_due_count"] == 0
    review_ids = [
        row["learning_item_id"]
        for row in under["entries"]
        if row["activity_kind"] == "review"
    ]
    new_ids = [
        row["learning_item_id"]
        for row in under["entries"]
        if row["activity_kind"] == "new_practice"
    ]
    assert set(review_ids) == {row["id"] for row in due_under}
    assert len(new_ids) == len(set(new_ids))
    assert set(new_ids) <= {row["id"] for row in news}
    assert all(
        row["skill_direction"] == "recognition"
        for row in under["entries"]
        if row["activity_kind"] == "new_practice"
    )

    extra_due = [
        _create_due_vocab(
            client,
            form=f"due-over-{index}",
            meaning=f"期限超{index}",
            occurred_at=NOW - timedelta(days=4),
        )
        for index in range(9)
    ]
    over = _today_plan(client, question_count=10, max_new_count=3)
    assert over["review_count"] == 10
    assert over["new_count"] == 0
    assert over["deferred_due_count"] == 3
    assert all(row["activity_kind"] == "review" for row in over["entries"])
    planned_due = {row["learning_item_id"] for row in over["entries"]}
    all_due = {row["id"] for row in [*due_under, *extra_due]}
    assert planned_due <= all_due
    assert len(all_due - planned_due) == 3


def test_phase5_direction_policy_keeps_due_direction_and_does_not_cross_errors(
    client: TestClient, store: TutorSqliteStore
):
    items = _seed_recommended_fixture(client, store)
    recognition_only = _create_item(
        client,
        canonical_form="livre",
        meaning_ja="本",
        level="A2",
    )
    _record_review(
        client,
        recognition_only["id"],
        exercise_type="meaning_recognition",
        result="incorrect",
        occurred_at=NOW - timedelta(days=1),
        event_id="evt-rec-only-error",
    )
    snapshots = {snap.learning_item_id: snap for snap in _snapshots(store, NOW)}
    rec_only = snapshots[recognition_only["id"]]
    assert rec_only.by_direction["recognition"].recent_incorrect_count >= 1
    assert rec_only.by_direction["production"].recent_incorrect_count == 0
    assert rec_only.by_direction["production"].is_unseen is True
    ranked = _ranked(store, NOW)
    production_of_rec_only = [
        row
        for row in ranked
        if row.learning_item_id == recognition_only["id"]
        and row.skill_direction == "production"
    ]
    assert production_of_rec_only
    assert all(
        "RECENT_ERROR" not in row.score.reason_codes for row in production_of_rec_only
    )

    session = _today_session(client, max_new_count=3)
    b_entry = next(
        row for row in session["entries"] if row["learning_item_id"] == items["B"]["id"]
    )
    assert b_entry["activity_kind"] == "review"
    assert b_entry["skill_direction"] == "production"
    b_exercise = next(
        row
        for row in session["exercises"]
        if row["learning_item_id"] == items["B"]["id"]
    )
    assert b_exercise["skill_direction"] == "production"
    new_entries = [
        row for row in session["entries"] if row["activity_kind"] == "new_practice"
    ]
    fixture_new = [
        row
        for row in new_entries
        if row["learning_item_id"]
        in {items["C"]["id"], items["D"]["id"], items["E"]["id"]}
    ]
    assert fixture_new
    assert all(row["skill_direction"] == "recognition" for row in fixture_new)


def test_phase5_stale_plan_transaction_and_duplicate(
    client: TestClient,
    store: TutorSqliteStore,
    monkeypatch: pytest.MonkeyPatch,
):
    due = _create_due_vocab(client, form="chat", meaning="猫")
    sibling = _create_due_vocab(client, form="chien", meaning="犬")
    _create_item(client, canonical_form="eau", meaning_ja="水")
    first = _today_session(client, question_count=10, max_new_count=0)
    due_entry = next(
        row for row in first["entries"] if row["learning_item_id"] == due["id"]
    )
    assert due_entry["activity_kind"] == "review"

    _set_item_status(store, due["id"], "suspended")
    after_inactive = _today_session(client, question_count=10, max_new_count=0)
    assert due["id"] not in {
        row["learning_item_id"] for row in after_inactive["entries"]
    }
    assert due["id"] not in {
        row["learning_item_id"] for row in after_inactive["exercises"]
    }
    skipped = {
        row["learning_item_id"]: row for row in after_inactive["skipped_entries"]
    }
    assert due["id"] not in skipped or skipped[due["id"]]["skip_reason"] == (
        "inactive_item"
    )
    assert sibling["id"] in {
        row["learning_item_id"] for row in after_inactive["entries"]
    }

    answered = _answer(
        client,
        store,
        sibling["id"],
        next(
            row["exercise_type"]
            for row in after_inactive["exercises"]
            if row["learning_item_id"] == sibling["id"]
        ),
        event_id="evt-phase5-review",
    )
    assert answered["review_schedule"]["review_count"] == 2
    refreshed = _today_session(client, question_count=10, max_new_count=0)
    assert sibling["id"] not in {
        row["learning_item_id"] for row in refreshed["entries"]
    }

    original_merge = Session.merge

    def fail_schedule_merge(
        self: Session, instance: object, **kwargs: object
    ) -> object:
        if isinstance(instance, ReviewScheduleRow):
            raise RuntimeError("schedule write failed")
        return original_merge(self, instance, **kwargs)

    leftover = _create_due_vocab(client, form="pont", meaning="橋")
    leftover_type = "meaning_recognition"
    original_rec = store.review_schedules.get(leftover["id"], "recognition")
    monkeypatch.setattr(Session, "merge", fail_schedule_merge)
    generated = _generated(store, leftover["id"], leftover_type)
    with pytest.raises(RuntimeError, match="schedule write failed"):
        client.post(
            f"/api/tutor/items/{leftover['id']}/exercises/{leftover_type}/answer",
            json={
                "answer": generated.answer_key.expected_answers[0],
                "id": "evt-should-rollback",
            },
        )
    monkeypatch.undo()
    event_ids = [
        event.id for event in store.learning_events.list_by_item(leftover["id"])
    ]
    assert "evt-should-rollback" not in event_ids
    assert store.review_schedules.get(leftover["id"], "recognition") == original_rec

    first_ok = _answer(
        client,
        store,
        leftover["id"],
        leftover_type,
        event_id="evt-dup-today",
    )
    assert first_ok["review_schedule"]["review_count"] == 2
    generated = _generated(store, leftover["id"], leftover_type)
    dup = client.post(
        f"/api/tutor/items/{leftover['id']}/exercises/{leftover_type}/answer",
        json={
            "answer": generated.answer_key.expected_answers[0],
            "id": "evt-dup-today",
        },
    )
    assert dup.status_code == 409
    state = store.learner_states.get(leftover["id"])
    assert state is not None
    assert state.by_direction["recognition"].attempt_count == 2


def test_phase5_existing_quiz_practice_review_and_tts_contracts_are_unchanged(
    client: TestClient, store: TutorSqliteStore, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _seed_recommended_fixture(client, store)

    question = client.get("/api/questions/next")
    assert question.status_code == 200
    assert {"verb", "tense", "pronoun"} <= set(question.json())

    check = client.post(
        "/api/answers/check",
        json={
            "verb": "être",
            "tense": "présent",
            "pronoun": "je",
            "answer": "suis",
        },
    )
    assert check.status_code == 200
    assert check.json()["correct"] is True

    noun = client.get("/api/nouns/next")
    assert noun.status_code == 200
    assert noun.json()["noun"] in NOUNS

    noun_check = client.post(
        "/api/nouns/check",
        json={"noun": "livre", "answer": "masculine"},
    )
    assert noun_check.status_code == 200
    assert noun_check.json()["correct"] is True

    article = client.get("/api/nouns/article/next")
    assert article.status_code == 200
    assert "noun" in article.json()

    article_check = client.post(
        "/api/nouns/article/check",
        json={"noun": "livre", "answer": "un livre"},
    )
    assert article_check.status_code == 200
    assert article_check.json()["correct"] is True

    tts = client.get("/api/tts/speak?text=bonjour")
    assert tts.status_code == 503
    assert "OPENAI_API_KEY" in tts.json()["detail"]

    practice = client.post("/api/tutor/practice/sessions", json={"question_count": 5})
    assert practice.status_code == 200, practice.text
    assert practice.json()["generated_count"] >= 1

    review = client.post("/api/tutor/review/sessions", json={"question_count": 5})
    assert review.status_code == 200, review.text
    assert review.json()["generated_count"] >= 1
    queue = client.get("/api/tutor/reviews/queue")
    assert queue.status_code == 200
    assert queue.json()["summary"]["total_due"] >= 1
    assert client.get("/api/tutor/sources").status_code == 200


def test_phase5_today_endpoints_exist_without_now_or_llm_ranking():
    with TestClient(app) as http:
        spec = http.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/tutor/today" in paths
    assert "/api/tutor/today/sessions" in paths
    assert "/api/tutor/practice/sessions" in paths
    assert "/api/tutor/review/sessions" in paths
    today_get = paths["/api/tutor/today"]["get"]
    param_names = {row["name"] for row in today_get.get("parameters", [])}
    assert "now" not in param_names
    forbidden = (
        "/api/tutor/reviews/today",
        "/api/tutor/recommendations",
        "/api/tutor/ranking",
        "/api/tutor/sources/url",
        "/api/tutor/sources/pdf",
        "/api/tutor/sources/youtube",
    )
    for path in forbidden:
        assert path not in paths, path


def test_phase5_ranking_modules_are_llm_independent():
    import ast
    import inspect

    import app.domain.daily_learning_plan as daily_learning_plan
    import app.domain.recommendation_ranking as recommendation_ranking
    import app.domain.recommendation_signal as recommendation_signal
    import app.domain.today_session as today_session
    import app.services.today_learning_service as today_learning_service

    forbidden = {"openai", "anthropic", "langchain", "litellm"}

    def imported_top_levels(module: object) -> set[str]:
        tree = ast.parse(inspect.getsource(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
        return names

    for module in (
        recommendation_signal,
        recommendation_ranking,
        daily_learning_plan,
        today_session,
        today_learning_service,
    ):
        found = imported_top_levels(module) & forbidden
        assert not found, f"{module.__name__} imports {found}"

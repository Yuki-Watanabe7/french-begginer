"""Source 単位の学習成果サマリー（Issue #205）。"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_learning_item_extractor, get_tutor_store
from app.domain.source_learning_summary import (
    ATTRIBUTION,
    POLICY_VERSION,
    InvalidSourceLearningInputError,
    summarize_source_learning,
)
from app.domain.tutor import (
    EvidenceSpan,
    LearnerState,
    LearningEvent,
    LearningItem,
    LearningItemCandidate,
    ReviewSchedule,
    SourceDocument,
    SourceRef,
    apply_review_event,
)
from app.main import app
from app.repositories.sqlite import TutorSqliteStore
from app.services.candidate_service import build_candidate_service
from app.services.exceptions import TutorNotFoundError
from app.services.extraction_prompt import EXTRACTION_VERSION
from app.services.extraction_schema import ExtractedCandidate, ExtractedEvidenceSpan
from app.services.extraction_service import ExtractionService
from app.services.extractors import ExtractorResult
from app.services.source_learning_summary_service import (
    build_source_learning_summary_service,
)
from app.services.tutor_service import build_tutor_service

NOW = datetime(2026, 10, 18, tzinfo=UTC)
DUE_AT = NOW - timedelta(days=2)
FUTURE = NOW + timedelta(days=3)
CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."


def _item(
    item_id: str,
    *source_ids: str,
    status: str = "active",
) -> LearningItem:
    return LearningItem(
        id=item_id,
        item_type="vocabulary",
        canonical_form=item_id,
        meaning_ja="意味",
        status=status,  # type: ignore[arg-type]
        source_refs=[
            SourceRef(source_document_id=source_id) for source_id in source_ids
        ],
    )


def _candidate(source_id: str, status: str, candidate_id: str) -> LearningItemCandidate:
    return LearningItemCandidate(
        id=candidate_id,
        source_document_id=source_id,
        item_type="vocabulary",
        canonical_form=candidate_id,
        meaning_ja="意味",
        evidence_span=EvidenceSpan(start=0, end=1),
        extraction_version="extract-v1",
        status=status,  # type: ignore[arg-type]
    )


def _state(item_id: str, steps: list[tuple[str, str, datetime]]) -> LearnerState:
    state: LearnerState | None = None
    for exercise_type, result, occurred_at in steps:
        event = LearningEvent(
            learning_item_id=item_id,
            exercise_type=exercise_type,  # type: ignore[arg-type]
            result=result,  # type: ignore[arg-type]
            occurred_at=occurred_at,
        )
        state = apply_review_event(state, event)
    assert state is not None
    return state


def _schedule(item_id: str, direction: str, due_at: datetime) -> ReviewSchedule:
    return ReviewSchedule(
        learning_item_id=item_id,
        skill_direction=direction,  # type: ignore[arg-type]
        due_at=due_at,
        interval_days=1,
    )


def _summary(source_id: str = "source-a", **kwargs):
    return summarize_source_learning(
        source_id,
        candidates=kwargs.get("candidates", ()),
        items=kwargs.get("items", ()),
        states=kwargs.get("states", {}),
        schedules=kwargs.get("schedules", {}),
        known_item_ids=kwargs.get("known", frozenset()),
        now=kwargs.get("now", NOW),
    )


def test_source_summary_counts_each_related_item_once() -> None:
    studied = _item("studied", "source-a", "source-a", "source-b")
    state = _state(
        studied.id,
        [
            ("meaning_recognition", "correct", NOW - timedelta(days=4)),
            ("ja_to_fr", "incorrect", NOW - timedelta(days=3)),
        ],
    )
    other = _item("other", "source-c")
    other_state = _state(other.id, [("ja_to_fr", "correct", NOW - timedelta(days=1))])
    summary = _summary(
        items=[studied, other],
        states={studied.id: state, other.id: other_state},
        schedules={
            studied.id: (
                _schedule(studied.id, "recognition", DUE_AT),
                _schedule(studied.id, "production", FUTURE),
            )
        },
        candidates=[
            _candidate("source-a", "accepted", "cand-accepted"),
            _candidate("source-a", "accepted", "cand-accepted-2"),
        ],
    )

    assert summary.attempts == 2
    assert summary.correct_count == 1
    assert summary.correct_rate == 0.5
    assert summary.accepted_item_count == 1
    assert summary.accepted_candidate_count == 2
    assert summary.started_item_count == 1
    assert len(studied.source_refs) == 3


def test_accepted_rejected_unseen_and_due() -> None:
    unseen = _item("unseen", "source-a")
    active = _item("active", "source-a")
    suspended = _item("suspended", "source-a", status="suspended")
    mastered = _item("mastered", "source-a", status="mastered")
    known = _item("known", "source-a")
    active_state = _state(
        active.id, [("meaning_recognition", "correct", NOW - timedelta(days=4))]
    )
    suspended_state = _state(
        suspended.id, [("ja_to_fr", "incorrect", NOW - timedelta(days=4))]
    )
    mastered_state = _state(
        mastered.id, [("ja_to_fr", "correct", NOW - timedelta(days=4))]
    )
    known_state = _state(
        known.id, [("meaning_recognition", "incorrect", NOW - timedelta(days=4))]
    )
    summary = _summary(
        items=[unseen, active, suspended, mastered, known],
        states={
            active.id: active_state,
            suspended.id: suspended_state,
            mastered.id: mastered_state,
            known.id: known_state,
        },
        schedules={
            active.id: (_schedule(active.id, "recognition", DUE_AT),),
            suspended.id: (_schedule(suspended.id, "production", DUE_AT),),
            mastered.id: (_schedule(mastered.id, "production", DUE_AT),),
            known.id: (_schedule(known.id, "recognition", DUE_AT),),
            unseen.id: (_schedule(unseen.id, "production", FUTURE),),
        },
        known=frozenset({known.id}),
        candidates=[
            _candidate("source-a", "candidate", "pending"),
            _candidate("source-a", "rejected", "rejected"),
            _candidate("source-a", "accepted", "accepted"),
        ],
    )

    assert summary.candidate_count == 3
    assert summary.pending_candidate_count == 1
    assert summary.rejected_item_count == 1
    assert summary.accepted_candidate_count == 1
    assert summary.accepted_item_count == 5
    assert summary.unseen_item_count == 1
    assert summary.active_item_count == 1
    assert summary.suspended_item_count == 1
    assert summary.mastered_or_known_count == 2
    assert summary.started_item_count == 4
    assert summary.due_direction_count == 2
    assert summary.recognition.due_count == 2
    assert summary.production.due_count == 0
    assert summary.recent_activity_at == NOW - timedelta(days=4)


def test_recognition_and_production_stay_separate() -> None:
    item = _item("both", "source-a")
    state = _state(
        item.id,
        [
            ("meaning_recognition", "correct", NOW - timedelta(days=5)),
            ("fr_to_ja", "correct", NOW - timedelta(days=4)),
            ("ja_to_fr", "incorrect", NOW - timedelta(days=3)),
            ("cloze", "incorrect", NOW - timedelta(hours=1)),
        ],
    )
    summary = _summary(
        items=[item],
        states={item.id: state},
        schedules={
            item.id: (
                _schedule(item.id, "recognition", DUE_AT),
                _schedule(item.id, "production", NOW),
            )
        },
    )

    assert summary.recognition.attempt_count == 2
    assert summary.recognition.correct_count == 2
    assert summary.recognition.correct_rate == 1.0
    assert summary.recognition.due_count == 1
    assert summary.production.attempt_count == 2
    assert summary.production.correct_count == 0
    assert summary.production.correct_rate == 0.0
    assert summary.production.due_count == 1
    assert summary.attempts == 4
    assert summary.correct_rate == 0.5
    assert summary.due_direction_count == 2
    assert summary.recent_activity_at == NOW - timedelta(hours=1)


def test_multi_source_item_is_not_double_counted_inside_one_summary() -> None:
    shared = _item("shared", "source-a", "source-a", "source-b")
    only_a = _item("only-a", "source-a")
    shared_state = _state(
        shared.id,
        [
            ("ja_to_fr", "correct", NOW - timedelta(days=3)),
            ("ja_to_fr", "incorrect", NOW - timedelta(days=2)),
        ],
    )
    only_state = _state(
        only_a.id, [("meaning_recognition", "correct", NOW - timedelta(days=1))]
    )
    states = {shared.id: shared_state, only_a.id: only_state}
    items = [shared, only_a]
    summary_a = _summary(items=items, states=states)
    summary_b = _summary("source-b", items=items, states=states)

    assert summary_a.attempts == 3
    assert summary_b.attempts == 2
    assert summary_a.accepted_item_count == 2
    assert summary_b.accepted_item_count == 1
    assert summary_a.attempts + summary_b.attempts == 5


def test_source_without_events_has_no_rate_or_activity() -> None:
    summary = _summary(
        items=[_item("fresh", "source-a")],
        candidates=[_candidate("source-a", "candidate", "pending")],
    )

    assert summary.attempts == 0
    assert summary.correct_count == 0
    assert summary.correct_rate is None
    assert summary.recent_activity_at is None
    assert summary.unseen_item_count == 1
    assert summary.started_item_count == 0
    assert summary.due_direction_count == 0
    assert summary.recognition.correct_rate is None
    assert summary.production.attempt_count == 0
    assert summary.attribution == ATTRIBUTION
    assert summary.policy_version == POLICY_VERSION


def test_explicit_known_stays_due_and_mastered_does_not() -> None:
    known = _item("known", "source-a")
    mastered = _item("mastered", "source-a", status="mastered")
    known_state = _state(known.id, [("ja_to_fr", "incorrect", NOW - timedelta(days=2))])
    mastered_state = _state(
        mastered.id, [("ja_to_fr", "correct", NOW - timedelta(days=2))]
    )
    summary = _summary(
        items=[known, mastered],
        states={known.id: known_state, mastered.id: mastered_state},
        schedules={
            known.id: (_schedule(known.id, "production", DUE_AT),),
            mastered.id: (_schedule(mastered.id, "production", DUE_AT),),
        },
        known=frozenset({known.id, mastered.id}),
    )

    assert summary.mastered_or_known_count == 2
    assert summary.active_item_count == 0
    assert summary.due_direction_count == 1
    assert summary.production.due_count == 1
    assert summary.started_item_count == 2


def test_same_inputs_are_deterministic() -> None:
    item = _item("item", "source-a")
    state = _state(item.id, [("cloze", "correct", NOW - timedelta(days=1))])
    kwargs = {
        "items": [item],
        "states": {item.id: state},
        "candidates": [_candidate("source-a", "rejected", "nope")],
        "schedules": {item.id: (_schedule(item.id, "production", FUTURE),)},
    }
    assert _summary(**kwargs) == _summary(**kwargs)


def test_invalid_inputs_are_rejected() -> None:
    item = _item("item", "source-a")
    with pytest.raises(InvalidSourceLearningInputError, match="timezone-aware"):
        _summary(now=datetime(2026, 10, 18))
    with pytest.raises(InvalidSourceLearningInputError, match="別 Source"):
        _summary(candidates=[_candidate("source-b", "candidate", "other")])
    with pytest.raises(InvalidSourceLearningInputError, match="重複"):
        _summary(items=[item, item])
    with pytest.raises(InvalidSourceLearningInputError, match="Candidate が重複"):
        pending = _candidate("source-a", "candidate", "same")
        _summary(candidates=[pending, pending])
    with pytest.raises(InvalidSourceLearningInputError, match="direction が重複"):
        _summary(
            items=[item],
            schedules={
                item.id: (
                    _schedule(item.id, "recognition", DUE_AT),
                    _schedule(item.id, "recognition", FUTURE),
                )
            },
        )


def test_summary_does_not_branch_on_source_type() -> None:
    import app.domain.source_learning_summary as domain_module
    import app.services.source_learning_summary_service as service_module

    forbidden = {
        "openai",
        "fastapi",
        "sqlalchemy",
        "app.api",
        "app.persistence",
        "app.ingestion",
    }
    for module in (domain_module, service_module):
        names: set[str] = set()
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
                names.add(node.module)
        assert not (names & forbidden)
        source = inspect.getsource(module)
        assert "source_type" not in source
        assert "web_url" not in source
        assert "datetime.now" not in source
    assert "list_by_item" not in inspect.getsource(service_module)
    assert "utcnow" not in inspect.getsource(domain_module)


@dataclass
class FakeLearningItemExtractor:
    result: ExtractorResult | None = None
    seen_sources: list[SourceDocument] = field(default_factory=list)

    def extract(self, source: SourceDocument) -> ExtractorResult:
        self.seen_sources.append(source)
        assert self.result is not None
        return self.result


def _span_for(fragment: str) -> ExtractedEvidenceSpan:
    start = CONTENT.index(fragment)
    return ExtractedEvidenceSpan(start=start, end=start + len(fragment))


def _extracted() -> ExtractedCandidate:
    return ExtractedCandidate(
        item_type="expression",
        canonical_form="se rendre compte",
        meaning_ja="〜に気づく",
        evidence_span=_span_for("rendu compte"),
        confidence=0.9,
    )


def test_persisted_summary_counts_accept_reject_and_due(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'summary.db'}"
    store = TutorSqliteStore(url)
    tutor = build_tutor_service(store, clock=lambda: NOW)
    service = build_source_learning_summary_service(store, clock=lambda: NOW)
    source = tutor.create_source(title="記事", content="Bonjour.")
    pending = LearningItemCandidate(
        source_document_id=source.id,
        item_type="vocabulary",
        canonical_form="bonjour",
        meaning_ja="こんにちは",
        evidence_span=EvidenceSpan(start=0, end=7),
        extraction_version="extract-v1",
        status="candidate",
    )
    rejected = LearningItemCandidate(
        source_document_id=source.id,
        item_type="vocabulary",
        canonical_form="salut",
        meaning_ja="やあ",
        evidence_span=EvidenceSpan(start=0, end=7),
        extraction_version="extract-v1",
        status="rejected",
    )
    store.learning_item_candidates.create_many([pending, rejected])
    unseen = tutor.create_item(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    studied = tutor.create_item(
        item_type="vocabulary",
        canonical_form="chat",
        meaning_ja="猫",
        source_refs=[
            SourceRef(source_document_id=source.id),
            SourceRef(source_document_id=source.id),
        ],
    )
    tutor.record_review(
        studied.id,
        exercise_type="meaning_recognition",
        result="correct",
        occurred_at=NOW - timedelta(days=4),
    )
    tutor.record_review(
        studied.id,
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=3),
    )
    known = tutor.create_item(
        item_type="vocabulary",
        canonical_form="maison",
        meaning_ja="家",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    tutor.record_review(
        known.id,
        exercise_type="cloze",
        result="incorrect",
        occurred_at=NOW - timedelta(days=3),
    )
    tutor.mark_known(known.id)
    mastered = tutor.create_item(
        item_type="vocabulary",
        canonical_form="ami",
        meaning_ja="友",
        status="mastered",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    tutor.record_review(
        mastered.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW - timedelta(days=5),
    )
    tutor.create_item(
        item_type="vocabulary",
        canonical_form="eau",
        meaning_ja="水",
        status="suspended",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    other = tutor.create_source(title="別", content="Autre texte.")
    tutor.create_item(
        item_type="vocabulary",
        canonical_form="autre",
        meaning_ja="別",
        source_refs=[SourceRef(source_document_id=other.id)],
    )

    summary = service.summarize(source.id, now=NOW)
    assert summary.candidate_count == 2
    assert summary.pending_candidate_count == 1
    assert summary.rejected_item_count == 1
    assert summary.accepted_item_count == 5
    assert summary.unseen_item_count == 1
    assert unseen.id
    assert summary.active_item_count == 1
    assert summary.suspended_item_count == 1
    assert summary.mastered_or_known_count == 2
    assert summary.started_item_count == 3
    assert summary.due_direction_count == 3
    assert summary.recognition.due_count == 1
    assert summary.production.due_count == 2
    assert summary.recognition.attempt_count == 1
    assert summary.recognition.correct_rate == 1.0
    assert summary.production.attempt_count == 3
    assert summary.production.correct_count == 1
    assert summary.attempts == 4
    assert len(store.learning_events.list_by_item(studied.id)) == 2
    assert summary.recent_activity_at == NOW - timedelta(days=3)
    store.engine.dispose()

    reopened = TutorSqliteStore(url)
    again = build_source_learning_summary_service(
        reopened, clock=lambda: NOW
    ).summarize(source.id, now=NOW)
    assert again == summary
    reopened.engine.dispose()


def test_summary_is_the_same_for_url_pdf_transcript_and_conversation() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: NOW)
    service = build_source_learning_summary_service(store, clock=lambda: NOW)
    comparable = []
    for source_type in ("web_url", "pdf", "youtube_transcript", "conversation_log"):
        document = store.source_documents.create(
            SourceDocument(
                source_type=source_type,  # type: ignore[arg-type]
                title=source_type,
                content="Bonjour.",
            )
        )
        store.learning_item_candidates.create(
            LearningItemCandidate(
                source_document_id=document.id,
                item_type="vocabulary",
                canonical_form="bonjour",
                meaning_ja="こんにちは",
                evidence_span=EvidenceSpan(start=0, end=7),
                extraction_version="extract-v1",
            )
        )
        item = tutor.create_item(
            item_type="vocabulary",
            canonical_form=f"mot-{source_type}",
            meaning_ja="語",
            source_refs=[SourceRef(source_document_id=document.id)],
        )
        tutor.record_review(
            item.id,
            exercise_type="meaning_recognition",
            result="correct",
            occurred_at=NOW - timedelta(days=4),
        )
        tutor.record_review(
            item.id,
            exercise_type="ja_to_fr",
            result="incorrect",
            occurred_at=NOW - timedelta(days=3),
        )
        summary = service.summarize(document.id, now=NOW)
        comparable.append(summary.model_copy(update={"source_id": "same"}))

    assert comparable[0] == comparable[1] == comparable[2] == comparable[3]
    assert comparable[0].due_direction_count == 2
    assert comparable[0].recognition.correct_rate == 1.0
    assert comparable[0].production.correct_rate == 0.0
    store.engine.dispose()


def test_merged_multi_source_item_keeps_events_once() -> None:
    store = TutorSqliteStore.in_memory()
    tutor = build_tutor_service(store, clock=lambda: NOW)
    service = build_source_learning_summary_service(store, clock=lambda: NOW)
    fake = FakeLearningItemExtractor(
        result=ExtractorResult(
            candidates=(_extracted(),),
            provider="fake",
            model="fake",
            extraction_version=EXTRACTION_VERSION,
        )
    )
    candidates = build_candidate_service(store, ExtractionService(fake))
    source_a = tutor.create_source(title="A", content=CONTENT)
    source_b = tutor.create_source(title="B", content=CONTENT)
    accepted = candidates.accept(
        candidates.extract_for_source(source_a.id).created[0].candidate.id
    )
    assert accepted.merged is False
    tutor.record_review(
        accepted.item.id,
        exercise_type="meaning_recognition",
        result="incorrect",
        occurred_at=NOW - timedelta(days=4),
    )
    tutor.record_review(
        accepted.item.id,
        exercise_type="ja_to_fr",
        result="correct",
        occurred_at=NOW - timedelta(days=3),
    )
    merged = candidates.accept(
        candidates.extract_for_source(source_b.id).created[0].candidate.id
    )
    assert merged.merged is True
    only_a = tutor.create_item(
        item_type="vocabulary",
        canonical_form="stratégie",
        meaning_ja="戦略",
        source_refs=[SourceRef(source_document_id=source_a.id)],
    )
    tutor.record_review(
        only_a.id,
        exercise_type="cloze",
        result="incorrect",
        occurred_at=NOW - timedelta(days=3),
    )

    summary_a = service.summarize(source_a.id, now=NOW)
    summary_b = service.summarize(source_b.id, now=NOW)
    assert summary_a.accepted_item_count == 2
    assert summary_b.accepted_item_count == 1
    assert summary_a.accepted_candidate_count == 1
    assert summary_b.accepted_candidate_count == 1
    assert summary_a.attempts == 3
    assert summary_b.attempts == 2
    assert len(store.learning_events.list_by_item(accepted.item.id)) == 2
    assert summary_a.recognition.correct_rate == 0.0
    assert summary_b.production.correct_rate == 1.0
    assert summary_b.due_direction_count == 2
    store.engine.dispose()


def test_missing_source_is_not_found() -> None:
    store = TutorSqliteStore.in_memory()
    service = build_source_learning_summary_service(store, clock=lambda: NOW)
    with pytest.raises(TutorNotFoundError):
        service.summarize("missing", now=NOW)
    store.engine.dispose()


@pytest.fixture
def store() -> Iterator[TutorSqliteStore]:
    database = TutorSqliteStore.in_memory()
    yield database
    database.engine.dispose()


@pytest.fixture
def client(store: TutorSqliteStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_tutor_store] = lambda: store
    app.dependency_overrides[get_learning_item_extractor] = lambda: (
        FakeLearningItemExtractor()
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_learning_summary_api_returns_related_current_state(
    client: TestClient, store: TutorSqliteStore
) -> None:
    tutor = build_tutor_service(store, clock=lambda: NOW)
    source = tutor.create_source(title="記事", content="Bonjour.")
    empty = client.get(f"/api/tutor/sources/{source.id}/learning-summary")
    assert empty.status_code == 200
    body = empty.json()
    assert body["attempts"] == 0
    assert body["correct_rate"] is None
    assert body["recent_activity_at"] is None
    assert body["attribution"] == ATTRIBUTION
    assert body["policy_version"] == POLICY_VERSION

    item = tutor.create_item(
        item_type="vocabulary",
        canonical_form="chat",
        meaning_ja="猫",
        source_refs=[
            SourceRef(source_document_id=source.id),
            SourceRef(source_document_id=source.id),
        ],
    )
    tutor.record_review(
        item.id,
        exercise_type="meaning_recognition",
        result="correct",
        occurred_at=NOW - timedelta(days=10),
    )
    tutor.record_review(
        item.id,
        exercise_type="ja_to_fr",
        result="incorrect",
        occurred_at=NOW - timedelta(days=9),
    )
    fresh = tutor.create_item(
        item_type="vocabulary",
        canonical_form="livre",
        meaning_ja="本",
        source_refs=[SourceRef(source_document_id=source.id)],
    )
    filled = client.get(f"/api/tutor/sources/{source.id}/learning-summary")
    ignored_now = client.get(
        f"/api/tutor/sources/{source.id}/learning-summary",
        params={"now": "2000-01-01T00:00:00Z"},
    )
    assert filled.status_code == 200
    assert filled.json() == ignored_now.json()
    parsed_service = build_source_learning_summary_service(store)
    parsed = parsed_service.summarize(source.id)
    assert filled.json()["accepted_item_count"] == 2
    assert filled.json()["unseen_item_count"] == 1
    assert filled.json()["attempts"] == 2
    assert filled.json()["due_direction_count"] == 2
    assert filled.json()["recognition"]["correct_rate"] == 1.0
    assert filled.json()["production"]["correct_rate"] == 0.0
    assert len(store.learning_events.list_by_item(item.id)) == 2
    assert fresh.id
    assert parsed.attempts == 2

    missing = client.get("/api/tutor/sources/missing-source/learning-summary")
    assert missing.status_code == 404

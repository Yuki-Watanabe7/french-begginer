import type {
  ActivityKind,
  ReasonCode,
  SkillDirection,
  TodayLearningPlanView,
  TodayLearningSession,
  TodayPlanEntryView,
} from '../types'
import type { ExerciseView } from '../types'

export function todayPlanEntryFixture(
  overrides: Partial<TodayPlanEntryView> = {},
): TodayPlanEntryView {
  return {
    learning_item_id: 'item-vocab',
    canonical_form: 'livre',
    meaning_ja: '本',
    item_type: 'vocabulary',
    activity_kind: 'review',
    skill_direction: 'recognition',
    selected_exercise_type: 'meaning_recognition',
    reason_codes: ['OVERDUE_REVIEW'],
    explanation: '復習時期を迎えています。',
    source_titles: ['Le Monde'],
    ...overrides,
  }
}

export function todayPlanFixture(
  overrides: Partial<TodayLearningPlanView> & {
    review_count?: number
    new_count?: number
    deferred_due_count?: number
    reason_codes?: ReasonCode[]
  } = {},
): TodayLearningPlanView {
  const reviewCount = overrides.review_count ?? 0
  const newCount = overrides.new_count ?? 0
  const entries =
    overrides.entries ??
    [
      ...Array.from({ length: reviewCount }, (_, index) =>
        todayPlanEntryFixture({
          learning_item_id: `item-review-${index + 1}`,
          canonical_form: index === 0 ? 'livre' : `item-${index + 1}`,
          activity_kind: 'review' as ActivityKind,
          skill_direction: (index % 2 === 0 ? 'recognition' : 'production') as SkillDirection,
          reason_codes: overrides.reason_codes ?? ['OVERDUE_REVIEW'],
        }),
      ),
      ...Array.from({ length: newCount }, (_, index) =>
        todayPlanEntryFixture({
          learning_item_id: `item-new-${index + 1}`,
          canonical_form: index === 0 ? 'bonjour' : `nouveau-${index + 1}`,
          activity_kind: 'new_practice',
          skill_direction: 'recognition',
          selected_exercise_type: 'meaning_recognition',
          reason_codes: overrides.reason_codes ?? ['RECENT_SOURCE'],
          explanation: '最近追加した教材に出てきた表現です。',
        }),
      ),
    ]
  const review = entries.filter(row => row.activity_kind === 'review').length
  const fresh = entries.filter(row => row.activity_kind === 'new_practice').length
  return {
    generated_at: '2026-09-06T00:00:00+00:00',
    requested_count: overrides.requested_count ?? 10,
    total_count: overrides.total_count ?? entries.length,
    review_count: review,
    new_count: fresh,
    deferred_due_count: overrides.deferred_due_count ?? 0,
    entries,
    summary_reason_codes:
      overrides.summary_reason_codes ??
      [...new Set(entries.flatMap(row => row.reason_codes))],
    policy_version: overrides.policy_version ?? 'plan-v1',
    explanation_summary:
      overrides.explanation_summary ??
      (entries.length === 0
        ? '候補がないため空の学習計画にした。'
        : `復習 ${review} 件を優先した。新規 ${fresh} 件を入れた。`),
  }
}

export const EMPTY_TODAY_PLAN = todayPlanFixture()

export function todaySessionFixture(
  exercises: ExerciseView[],
  entries: TodayPlanEntryView[] = [],
  overrides: Partial<TodayLearningSession> = {},
): TodayLearningSession {
  const aligned =
    entries.length === exercises.length
      ? entries
      : exercises.map((exercise, index) =>
          todayPlanEntryFixture({
            learning_item_id: exercise.learning_item_id,
            activity_kind: index === 0 ? 'review' : 'new_practice',
            skill_direction: exercise.skill_direction,
            selected_exercise_type: exercise.exercise_type,
          }),
        )
  const reviewCount = aligned.filter(row => row.activity_kind === 'review').length
  const newCount = aligned.filter(row => row.activity_kind === 'new_practice').length
  return {
    session_id: 'today-1',
    exercises,
    entries: aligned,
    skipped_entries: [],
    requested_count: exercises.length || 10,
    generated_count: exercises.length,
    review_count: reviewCount,
    new_count: newCount,
    deferred_due_count: 0,
    explanation_summary: `復習 ${reviewCount} 件を優先した。新規 ${newCount} 件を入れた。`,
    policy_version: 'plan-v1',
    generated_at: '2026-09-06T00:00:00+00:00',
    summary_reason_codes: [...new Set(aligned.flatMap(row => row.reason_codes))],
    ...overrides,
  }
}

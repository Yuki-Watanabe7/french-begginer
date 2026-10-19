import type { SourceLearningSummary } from '../types'

export const EMPTY_SOURCE_LEARNING_SUMMARY: SourceLearningSummary = {
  source_id: 'src-1',
  policy_version: 'source-learning-summary-v1',
  attribution: 'related_item_current_state',
  candidate_count: 0,
  pending_candidate_count: 0,
  accepted_candidate_count: 0,
  accepted_item_count: 0,
  rejected_item_count: 0,
  unseen_item_count: 0,
  active_item_count: 0,
  suspended_item_count: 0,
  mastered_or_known_count: 0,
  started_item_count: 0,
  due_direction_count: 0,
  attempts: 0,
  correct_count: 0,
  correct_rate: null,
  recognition: {
    skill_direction: 'recognition',
    attempt_count: 0,
    correct_count: 0,
    correct_rate: null,
    due_count: 0,
  },
  production: {
    skill_direction: 'production',
    attempt_count: 0,
    correct_count: 0,
    correct_rate: null,
    due_count: 0,
  },
  recent_activity_at: null,
}

export function sourceLearningSummaryFixture(
  overrides: Partial<SourceLearningSummary> = {},
): SourceLearningSummary {
  return {
    ...EMPTY_SOURCE_LEARNING_SUMMARY,
    ...overrides,
    recognition: overrides.recognition ?? EMPTY_SOURCE_LEARNING_SUMMARY.recognition,
    production: overrides.production ?? EMPTY_SOURCE_LEARNING_SUMMARY.production,
  }
}

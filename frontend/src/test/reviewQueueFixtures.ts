import type { ReviewQueue, ReviewQueueSummary } from '../types'

export function reviewQueueFixture(
  summary: Partial<ReviewQueueSummary> = {},
): ReviewQueue {
  const total_due = summary.total_due ?? 0
  return {
    entries: [],
    summary: {
      total_due,
      recognition_due: summary.recognition_due ?? 0,
      production_due: summary.production_due ?? 0,
      overdue_count: summary.overdue_count ?? 0,
    },
  }
}

export const EMPTY_REVIEW_QUEUE = reviewQueueFixture()

import { useCallback, useEffect, useState } from 'react'
import { fetchReviewQueue } from '../api/tutor'
import type { ReviewQueue, ReviewQueueSummary } from '../types'
import { tutorReviewQueueErrorMessage } from '../utils/tutor'

export type ReviewQueueStatus = 'loading' | 'error' | 'success'

const EMPTY_SUMMARY: ReviewQueueSummary = {
  total_due: 0,
  recognition_due: 0,
  production_due: 0,
  overdue_count: 0,
}

export function useReviewQueue() {
  const [status, setStatus] = useState<ReviewQueueStatus>('loading')
  const [queue, setQueue] = useState<ReviewQueue | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setStatus('loading')
    setError(null)
    try {
      const next = await fetchReviewQueue()
      if (signal?.cancelled) return
      setQueue(next)
      setStatus('success')
    } catch (err) {
      if (signal?.cancelled) return
      setError(tutorReviewQueueErrorMessage(err))
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    const signal = { cancelled: false }
    void load(signal)
    return () => {
      signal.cancelled = true
    }
  }, [load])

  return {
    status,
    queue,
    summary: queue?.summary ?? EMPTY_SUMMARY,
    error,
    retry: () => {
      void load()
    },
  }
}

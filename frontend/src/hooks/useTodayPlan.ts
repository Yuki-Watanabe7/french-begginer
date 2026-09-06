import { useCallback, useEffect, useState } from 'react'
import { fetchTodayPlan } from '../api/tutor'
import type { TodayLearningPlanView } from '../types'
import { tutorTodayPlanErrorMessage } from '../utils/tutor'

export type TodayPlanStatus = 'loading' | 'error' | 'success'

export function useTodayPlan() {
  const [status, setStatus] = useState<TodayPlanStatus>('loading')
  const [plan, setPlan] = useState<TodayLearningPlanView | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setStatus('loading')
    setError(null)
    try {
      const next = await fetchTodayPlan()
      if (signal?.cancelled) return
      setPlan(next)
      setStatus('success')
    } catch (err) {
      if (signal?.cancelled) return
      setError(tutorTodayPlanErrorMessage(err))
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
    plan,
    error,
    retry: () => {
      void load()
    },
  }
}

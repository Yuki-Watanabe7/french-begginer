import { useCallback, useEffect, useState } from 'react'
import { fetchTutorSources } from '../api/tutor'
import type { SourceSummary } from '../types'
import { tutorFetchErrorMessage } from '../utils/tutor'

export type TutorSourceListStatus = 'loading' | 'empty' | 'error' | 'success'

export function useTutorSourceList() {
  const [status, setStatus] = useState<TutorSourceListStatus>('loading')
  const [sources, setSources] = useState<SourceSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setStatus('loading')
    setError(null)
    try {
      const rows = await fetchTutorSources()
      if (signal?.cancelled) return
      setSources(rows)
      setStatus(rows.length === 0 ? 'empty' : 'success')
    } catch (err) {
      if (signal?.cancelled) return
      setSources([])
      setError(tutorFetchErrorMessage(err, 'list'))
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
    sources,
    error,
    retry: () => {
      void load()
    },
  }
}

import { useCallback, useEffect, useState } from 'react'
import { fetchTutorSource, isNotFoundError } from '../api/tutor'
import type { SourceDocument } from '../types'
import { tutorFetchErrorMessage } from '../utils/tutor'

export type TutorSourceDetailStatus = 'loading' | 'error' | 'not-found' | 'success'

export function useTutorSourceDetail(
  sourceId: string,
  initialSource?: SourceDocument | null,
) {
  const hasInitial = initialSource?.id === sourceId
  const [status, setStatus] = useState<TutorSourceDetailStatus>(
    hasInitial ? 'success' : 'loading',
  )
  const [source, setSource] = useState<SourceDocument | null>(
    hasInitial ? initialSource : null,
  )
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setStatus('loading')
    setError(null)
    try {
      const document = await fetchTutorSource(sourceId)
      if (signal?.cancelled) return
      setSource(document)
      setStatus('success')
    } catch (err) {
      if (signal?.cancelled) return
      setSource(null)
      if (isNotFoundError(err)) {
        setError(tutorFetchErrorMessage(err, 'detail'))
        setStatus('not-found')
        return
      }
      setError(tutorFetchErrorMessage(err, 'detail'))
      setStatus('error')
    }
  }, [sourceId])

  useEffect(() => {
    if (initialSource?.id === sourceId) {
      setSource(initialSource)
      setStatus('success')
      setError(null)
      return
    }

    const signal = { cancelled: false }
    void load(signal)
    return () => {
      signal.cancelled = true
    }
  }, [sourceId, initialSource, load])

  return {
    status,
    source,
    error,
    retry: () => {
      void load()
    },
  }
}

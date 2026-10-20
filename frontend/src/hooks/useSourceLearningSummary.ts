import { useCallback, useEffect, useState } from 'react'
import { ApiError, fetchSourceLearningSummary } from '../api/tutor'
import type { SourceLearningSummary } from '../types'

export type SourceLearningSummaryStatus = 'loading' | 'error' | 'success'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status >= 500) {
    return '学習状況を取得できませんでした。時間をおいて再度お試しください'
  }
  return '学習状況の取得に失敗しました。通信環境を確認して再度お試しください'
}

export function useSourceLearningSummary(sourceId: string) {
  const [status, setStatus] = useState<SourceLearningSummaryStatus>('loading')
  const [summary, setSummary] = useState<SourceLearningSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setStatus('loading')
    setError(null)
    try {
      const next = await fetchSourceLearningSummary(sourceId)
      if (signal?.cancelled) return
      setSummary(next)
      setStatus('success')
    } catch (err) {
      if (signal?.cancelled) return
      setSummary(null)
      setError(errorMessage(err))
      setStatus('error')
    }
  }, [sourceId])

  useEffect(() => {
    const signal = { cancelled: false }
    void load(signal)
    return () => {
      signal.cancelled = true
    }
  }, [load])

  return {
    status,
    summary,
    error,
    retry: () => {
      void load()
    },
  }
}

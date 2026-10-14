import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  acceptCandidate,
  clearItemKnown,
  extractCandidates,
  fetchCandidates,
  markItemKnown,
  rejectCandidate,
} from '../api/tutor'
import type {
  CandidateFilter,
  CandidateStatus,
  LearningItemCandidate,
} from '../types'
import {
  tutorCandidateActionErrorMessage,
  tutorCandidateFetchErrorMessage,
  tutorExtractErrorMessage,
  tutorKnownItemErrorMessage,
} from '../utils/tutor'

export interface CandidateKnownUi {
  itemId: string
  explicitKnown: boolean
  busy: boolean
  error: string | null
}

export type CandidateListStatus = 'loading' | 'error' | 'success'

function groupByStatus(rows: LearningItemCandidate[]): LearningItemCandidate[] {
  const buckets: Record<CandidateStatus, LearningItemCandidate[]> = {
    candidate: [],
    accepted: [],
    rejected: [],
  }
  for (const row of rows) {
    buckets[row.status].push(row)
  }
  return [...buckets.candidate, ...buckets.accepted, ...buckets.rejected]
}

function extractNoticeFromResult(
  createdCount: number,
  skippedCount: number,
): string | null {
  if (createdCount > 0) {
    return `${createdCount}件の新しい候補を抽出しました`
  }
  if (skippedCount > 0) {
    return '新しい候補はありません。既存の候補を表示しています'
  }
  return null
}

export function useTutorSourceCandidates(sourceId: string) {
  const [listStatus, setListStatus] = useState<CandidateListStatus>('loading')
  const [candidates, setCandidates] = useState<LearningItemCandidate[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractError, setExtractError] = useState<string | null>(null)
  const [extractNotice, setExtractNotice] = useState<string | null>(null)
  const [hasExtracted, setHasExtracted] = useState(false)
  const [filter, setFilter] = useState<CandidateFilter>('all')
  const [pendingIds, setPendingIds] = useState<ReadonlySet<string>>(new Set())
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})
  const [knownByCandidate, setKnownByCandidate] = useState<
    Record<string, CandidateKnownUi>
  >({})
  const extractingRef = useRef(false)
  const pendingRef = useRef(new Set<string>())
  const knownRef = useRef(knownByCandidate)
  const knownPendingRef = useRef(new Set<string>())
  knownRef.current = knownByCandidate

  const setKnown = useCallback(
    (
      updater: (
        prev: Record<string, CandidateKnownUi>,
      ) => Record<string, CandidateKnownUi>,
    ) => {
      setKnownByCandidate(prev => {
        const next = updater(prev)
        knownRef.current = next
        return next
      })
    },
    [],
  )

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    setListStatus('loading')
    setListError(null)
    try {
      const rows = await fetchCandidates(sourceId)
      if (signal?.cancelled) return
      setCandidates(groupByStatus(rows))
      setKnown(prev => mergeKnown(rows, prev))
      setListStatus('success')
    } catch (error) {
      if (signal?.cancelled) return
      setListError(tutorCandidateFetchErrorMessage(error))
      setListStatus('error')
    }
  }, [setKnown, sourceId])

  useEffect(() => {
    const signal = { cancelled: false }
    void load(signal)
    return () => {
      signal.cancelled = true
    }
  }, [load])

  const extract = useCallback(async () => {
    if (extractingRef.current) return
    extractingRef.current = true
    setIsExtracting(true)
    setExtractError(null)
    setExtractNotice(null)
    try {
      const result = await extractCandidates(sourceId)
      const rows = await fetchCandidates(sourceId)
      setCandidates(groupByStatus(rows))
      setKnown(prev => mergeKnown(rows, prev))
      setListStatus('success')
      setListError(null)
      setHasExtracted(true)
      setExtractNotice(
        extractNoticeFromResult(result.created.length, result.skipped.length),
      )
    } catch (error) {
      setExtractError(tutorExtractErrorMessage(error))
    } finally {
      extractingRef.current = false
      setIsExtracting(false)
    }
  }, [setKnown, sourceId])

  const runAction = useCallback(
    async (
      candidateId: string,
      action: () => Promise<LearningItemCandidate>,
    ) => {
      if (pendingRef.current.has(candidateId) || extractingRef.current) return
      pendingRef.current.add(candidateId)
      setPendingIds(new Set(pendingRef.current))
      setActionErrors(prev => {
        const next = { ...prev }
        delete next[candidateId]
        return next
      })
      try {
        const updated = await action()
        setCandidates(prev =>
          groupByStatus(prev.map(row => (row.id === candidateId ? updated : row))),
        )
      } catch (error) {
        setActionErrors(prev => ({
          ...prev,
          [candidateId]: tutorCandidateActionErrorMessage(error),
        }))
      } finally {
        pendingRef.current.delete(candidateId)
        setPendingIds(new Set(pendingRef.current))
      }
    },
    [],
  )

  const accept = useCallback(
    (candidateId: string) => {
      void runAction(candidateId, async () => {
        const result = await acceptCandidate(candidateId)
        setKnown(prev => ({
          ...prev,
          [candidateId]: {
            itemId: result.item.id,
            explicitKnown: result.candidate.explicit_known === true,
            busy: false,
            error: null,
          },
        }))
        return result.candidate
      })
    },
    [runAction, setKnown],
  )

  const changeKnown = useCallback(
    async (candidateId: string, mark: boolean) => {
      if (knownPendingRef.current.has(candidateId)) return
      const current = knownRef.current[candidateId]
      if (!current || current.explicitKnown === mark) return
      knownPendingRef.current.add(candidateId)
      const itemId = current.itemId
      setKnown(prev => ({
        ...prev,
        [candidateId]: { ...prev[candidateId], busy: true, error: null },
      }))
      try {
        const result = mark
          ? await markItemKnown(itemId)
          : await clearItemKnown(itemId)
        setKnown(prev => ({
          ...prev,
          [candidateId]: {
            itemId,
            explicitKnown: result.explicit_known,
            busy: false,
            error: null,
          },
        }))
      } catch (error) {
        setKnown(prev => {
          const row = prev[candidateId]
          if (!row) return prev
          return {
            ...prev,
            [candidateId]: {
              ...row,
              busy: false,
              error: tutorKnownItemErrorMessage(error),
            },
          }
        })
      } finally {
        knownPendingRef.current.delete(candidateId)
      }
    },
    [setKnown],
  )

  const reject = useCallback(
    (candidateId: string) => {
      void runAction(candidateId, () => rejectCandidate(candidateId))
    },
    [runAction],
  )

  const visibleCandidates = useMemo(() => {
    if (filter === 'all') return candidates
    return candidates.filter(row => row.status === filter)
  }, [candidates, filter])

  const counts = useMemo(
    () => ({
      all: candidates.length,
      candidate: candidates.filter(row => row.status === 'candidate').length,
      accepted: candidates.filter(row => row.status === 'accepted').length,
      rejected: candidates.filter(row => row.status === 'rejected').length,
    }),
    [candidates],
  )

  return {
    listStatus,
    candidates,
    visibleCandidates,
    counts,
    listError,
    isExtracting,
    extractError,
    extractNotice,
    hasExtracted,
    filter,
    setFilter,
    pendingIds,
    actionErrors,
    knownByCandidate,
    markKnown: (candidateId: string) => {
      void changeKnown(candidateId, true)
    },
    undoKnown: (candidateId: string) => {
      void changeKnown(candidateId, false)
    },
    retryList: () => {
      void load()
    },
    extract,
    accept,
    reject,
  }
}

function knownFromCandidate(row: LearningItemCandidate): CandidateKnownUi | null {
  if (!row.learning_item_id) return null
  return {
    itemId: row.learning_item_id,
    explicitKnown: row.explicit_known === true,
    busy: false,
    error: null,
  }
}

function mergeKnown(
  rows: LearningItemCandidate[],
  previous: Record<string, CandidateKnownUi>,
): Record<string, CandidateKnownUi> {
  const next: Record<string, CandidateKnownUi> = {}
  for (const row of rows) {
    const fromRow = knownFromCandidate(row)
    const existing = previous[row.id]
    if (existing?.busy) {
      next[row.id] = existing
      continue
    }
    if (fromRow) {
      next[row.id] = fromRow
    } else if (existing) {
      next[row.id] = { ...existing, busy: false }
    }
  }
  return next
}

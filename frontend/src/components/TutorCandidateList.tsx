import { TutorCandidateCard } from './TutorCandidateCard'
import {
  useTutorSourceCandidates,
  type CandidateKnownUi,
} from '../hooks/useTutorSourceCandidates'
import type { CandidateFilter, SourceSegment } from '../types'
import { evidenceProvenanceLabel } from '../utils/sourceIngestion'

interface Props {
  sourceId: string
  segments?: readonly SourceSegment[] | null
}

function knownControl(
  state: ReturnType<typeof useTutorSourceCandidates>,
  candidateId: string,
): {
  explicitKnown: boolean
  busy: boolean
  error: string | null
  onMark: () => void
  onUndo: () => void
} | null {
  const known: CandidateKnownUi | undefined = state.knownByCandidate[candidateId]
  if (!known) return null
  return {
    explicitKnown: known.explicitKnown,
    busy: known.busy || state.pendingIds.has(candidateId),
    error: known.error,
    onMark: () => state.markKnown(candidateId),
    onUndo: () => state.undoKnown(candidateId),
  }
}

const FILTERS: { id: CandidateFilter; label: string }[] = [
  { id: 'all', label: 'すべて' },
  { id: 'candidate', label: '未確認' },
  { id: 'accepted', label: '採用済み' },
  { id: 'rejected', label: '却下' },
]

export function TutorCandidateList({ sourceId, segments }: Props) {
  const state = useTutorSourceCandidates(sourceId)
  const hasAny = state.candidates.length > 0
  const extractLabel = state.isExtracting
    ? '抽出しています...'
    : hasAny || state.hasExtracted
      ? 'もう一度抽出する'
      : '学習候補を抽出'
  const emptyMessage = state.hasExtracted
    ? '学習候補は見つかりませんでした'
    : 'まだ学習候補がありません。抽出すると、覚える候補を確認できます'

  return (
    <section style={styles.section} aria-labelledby="tutor-candidates-heading">
      <h3 id="tutor-candidates-heading" style={styles.heading}>
        学習候補
      </h3>
      <p style={styles.help}>
        本文から覚える候補を取り出します。採用したものだけが学習項目になります。
        すでに知っているものは、新しい学習から外せます。あとから戻せます。
      </p>
      {(hasAny || state.hasExtracted) && (
        <p style={styles.reextractHint}>すでに採用・却下した候補はそのまま残ります</p>
      )}
      <button
        type="button"
        style={{
          ...styles.extractBtn,
          ...(state.isExtracting ? styles.btnDisabled : {}),
        }}
        disabled={state.isExtracting}
        aria-busy={state.isExtracting}
        onClick={() => {
          void state.extract()
        }}
      >
        {extractLabel}
      </button>
      {state.extractError && (
        <p style={styles.error} role="alert">
          {state.extractError}
        </p>
      )}
      {state.extractNotice && !state.extractError && (
        <p style={styles.notice} role="status">
          {state.extractNotice}
        </p>
      )}

      {state.listStatus === 'loading' && (
        <p style={styles.msg} role="status">
          学習候補を読み込み中...
        </p>
      )}

      {state.listStatus === 'error' && (
        <div style={styles.errorBox} role="alert">
          <p style={styles.errorText}>{state.listError}</p>
          <button type="button" style={styles.retryBtn} onClick={state.retryList}>
            再試行
          </button>
        </div>
      )}

      {state.listStatus === 'success' && hasAny && (
        <div style={styles.filters} role="tablist" aria-label="候補の絞り込み">
          {FILTERS.map(item => {
            const selected = state.filter === item.id
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={selected}
                style={{
                  ...styles.filterChip,
                  ...(selected ? styles.filterChipSelected : {}),
                }}
                onClick={() => state.setFilter(item.id)}
              >
                {item.label} {state.counts[item.id]}
              </button>
            )
          })}
        </div>
      )}

      {state.listStatus === 'success' && !hasAny && (
        <p style={styles.empty} role="status">
          {emptyMessage}
        </p>
      )}

      {state.listStatus === 'success' && hasAny && state.visibleCandidates.length === 0 && (
        <p style={styles.empty} role="status">
          この条件の候補はありません
        </p>
      )}

      {state.listStatus === 'success' && state.visibleCandidates.length > 0 && (
        <ul style={styles.list}>
          {state.visibleCandidates.map(candidate => (
            <li key={candidate.id} style={styles.listItem}>
              <TutorCandidateCard
                candidate={candidate}
                evidenceProvenance={evidenceProvenanceLabel(segments, candidate.evidence_span)}
                isBusy={state.isExtracting || state.pendingIds.has(candidate.id)}
                actionError={state.actionErrors[candidate.id] ?? null}
                onAccept={() => state.accept(candidate.id)}
                onReject={() => state.reject(candidate.id)}
                known={knownControl(state, candidate.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const styles: Record<string, React.CSSProperties> = {
  section: {
    display: 'flex',
    flexDirection: 'column',
    margin: '8px 0 8px',
    width: '100%',
    boxSizing: 'border-box',
  },
  heading: {
    margin: '0 0 8px',
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  help: {
    margin: '0 0 8px',
    fontSize: 14,
    color: '#555',
    lineHeight: 1.5,
  },
  reextractHint: {
    margin: '0 0 12px',
    fontSize: 13,
    color: '#64748b',
    lineHeight: 1.5,
  },
  extractBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '14px 0',
    minHeight: 48,
    borderRadius: 14,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  btnDisabled: {
    opacity: 0.7,
    cursor: 'not-allowed',
  },
  error: {
    margin: '12px 0 0',
    color: '#b91c1c',
    fontSize: 14,
    background: '#fee2e2',
    borderRadius: 10,
    padding: '10px 12px',
    lineHeight: 1.5,
  },
  notice: {
    margin: '12px 0 0',
    color: '#065f46',
    fontSize: 14,
    background: '#d1fae5',
    borderRadius: 10,
    padding: '10px 12px',
    lineHeight: 1.5,
  },
  msg: {
    textAlign: 'center',
    color: '#666',
    fontSize: 15,
    margin: '16px 0 0',
  },
  errorBox: {
    textAlign: 'center',
    padding: 16,
    background: '#fff',
    borderRadius: 14,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    marginTop: 16,
  },
  errorText: {
    margin: '0 0 12px',
    color: '#444',
    fontSize: 15,
    lineHeight: 1.5,
  },
  retryBtn: {
    fontSize: 16,
    fontWeight: 700,
    padding: '10px 24px',
    minHeight: 44,
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  filters: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 16,
  },
  filterChip: {
    fontSize: 13,
    fontWeight: 700,
    minHeight: 40,
    padding: '8px 12px',
    borderRadius: 999,
    border: '1px solid #cbd5e1',
    background: '#fff',
    color: '#334155',
    cursor: 'pointer',
  },
  filterChipSelected: {
    background: '#1a56d6',
    border: '1px solid #1a56d6',
    color: '#fff',
  },
  empty: {
    margin: '16px 0 0',
    fontSize: 14,
    color: '#555',
    lineHeight: 1.5,
    textAlign: 'center',
    background: '#fff',
    borderRadius: 14,
    padding: 16,
  },
  list: {
    listStyle: 'none',
    margin: '16px 0 0',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  listItem: {
    margin: 0,
    padding: 0,
    width: '100%',
  },
}

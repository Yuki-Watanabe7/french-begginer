import type { LearningItemCandidate } from '../types'
import { KnownItemControl } from './KnownItemControl'
import {
  CANDIDATE_STATUS_LABELS,
  formatCandidateConfidence,
  LEARNING_ITEM_TYPE_LABELS,
} from '../utils/tutor'

interface Props {
  candidate: LearningItemCandidate
  evidenceProvenance?: string | null
  isBusy: boolean
  actionError: string | null
  onAccept: () => void
  onReject: () => void
  known?: {
    explicitKnown: boolean
    busy: boolean
    error: string | null
    onMark: () => void
    onUndo: () => void
  } | null
}

export function TutorCandidateCard({
  candidate,
  evidenceProvenance = null,
  isBusy,
  actionError,
  onAccept,
  onReject,
  known = null,
}: Props) {
  const typeLabel = LEARNING_ITEM_TYPE_LABELS[candidate.item_type]
  const statusLabel = CANDIDATE_STATUS_LABELS[candidate.status]
  const confidence = formatCandidateConfidence(candidate.confidence)
  const pending = candidate.status === 'candidate'

  return (
    <article style={styles.card} aria-label={`${typeLabel} ${candidate.canonical_form}`}>
      <div style={styles.badges}>
        <span style={{ ...styles.badge, ...TYPE_BADGE[candidate.item_type] }}>
          {typeLabel}
        </span>
        <span style={{ ...styles.badge, ...STATUS_BADGE[candidate.status] }}>
          {statusLabel}
        </span>
        {candidate.level && <span style={styles.metaBadge}>{candidate.level}</span>}
        {confidence && <span style={styles.metaBadge}>{confidence}</span>}
      </div>
      <p lang="fr" style={styles.canonical}>
        {candidate.canonical_form}
      </p>
      <p style={styles.meaning}>{candidate.meaning_ja}</p>
      {candidate.explanation_ja && (
        <p style={styles.explanation}>{candidate.explanation_ja}</p>
      )}
      {evidenceProvenance && <p style={styles.provenance}>{evidenceProvenance}</p>}
      <blockquote style={styles.evidence}>
        <span style={styles.evidenceLabel}>原文</span>
        <span lang="fr" style={styles.evidenceText}>
          {candidate.evidence_text}
        </span>
      </blockquote>
      {actionError && (
        <p style={styles.actionError} role="alert">
          {actionError}
        </p>
      )}
      {pending && (
        <div style={styles.actions}>
          <button
            type="button"
            style={{
              ...styles.acceptBtn,
              ...(isBusy ? styles.btnDisabled : {}),
            }}
            disabled={isBusy}
            onClick={onAccept}
          >
            採用する
          </button>
          <button
            type="button"
            style={{
              ...styles.rejectBtn,
              ...(isBusy ? styles.btnDisabled : {}),
            }}
            disabled={isBusy}
            onClick={onReject}
          >
            却下する
          </button>
        </div>
      )}
      {candidate.status === 'accepted' && known && (
        <KnownItemControl
          key={candidate.id}
          explicitKnown={known.explicitKnown}
          busy={known.busy}
          error={known.error}
          onMark={known.onMark}
          onUndo={known.onUndo}
        />
      )}
    </article>
  )
}

const TYPE_BADGE: Record<LearningItemCandidate['item_type'], React.CSSProperties> = {
  vocabulary: { background: '#e0e7ff', color: '#1a56d6' },
  expression: { background: '#ede9fe', color: '#6d28d9' },
  grammar: { background: '#ccfbf1', color: '#0f766e' },
  conjugation: { background: '#ffedd5', color: '#c2410c' },
}

const STATUS_BADGE: Record<LearningItemCandidate['status'], React.CSSProperties> = {
  candidate: { background: '#eff6ff', color: '#1a56d6' },
  accepted: { background: '#d1fae5', color: '#065f46' },
  rejected: { background: '#f3f4f6', color: '#4b5563' },
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    width: '100%',
    boxSizing: 'border-box',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    padding: '14px 16px',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  badges: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
  },
  badge: {
    fontSize: 12,
    fontWeight: 700,
    borderRadius: 999,
    padding: '4px 10px',
  },
  metaBadge: {
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 999,
    padding: '4px 10px',
    background: '#f3f4f6',
    color: '#444',
  },
  canonical: {
    margin: 0,
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a2e',
    lineHeight: 1.4,
  },
  meaning: {
    margin: 0,
    fontSize: 15,
    color: '#222',
    lineHeight: 1.5,
  },
  provenance: {
    margin: 0,
    fontSize: 12,
    fontWeight: 700,
    color: '#1a56d6',
    overflowWrap: 'anywhere',
  },
  explanation: {
    margin: 0,
    fontSize: 14,
    color: '#555',
    lineHeight: 1.5,
  },
  evidence: {
    margin: 0,
    padding: '10px 12px',
    background: '#f8fafc',
    borderLeft: '3px solid #93c5fd',
    borderRadius: 8,
  },
  evidenceLabel: {
    display: 'block',
    fontSize: 11,
    fontWeight: 700,
    color: '#64748b',
    marginBottom: 4,
  },
  evidenceText: {
    display: 'block',
    fontSize: 14,
    color: '#1a1a2e',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  actionError: {
    margin: 0,
    color: '#b91c1c',
    fontSize: 13,
    lineHeight: 1.5,
  },
  actions: {
    display: 'flex',
    gap: 8,
    marginTop: 4,
  },
  acceptBtn: {
    flex: 1,
    minHeight: 44,
    fontSize: 16,
    fontWeight: 700,
    border: 'none',
    borderRadius: 12,
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
  },
  rejectBtn: {
    flex: 1,
    minHeight: 44,
    fontSize: 16,
    fontWeight: 700,
    border: '1px solid #cbd5e1',
    borderRadius: 12,
    background: '#fff',
    color: '#475569',
    cursor: 'pointer',
  },
  btnDisabled: {
    opacity: 0.65,
    cursor: 'not-allowed',
  },
}

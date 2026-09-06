import { useTodayPlan } from '../hooks/useTodayPlan'
import type { TodayPlanEntryView } from '../types'
import {
  MAX_TODAY_PLAN_PREVIEW,
  todayActivityLabel,
  visibleReasonLabels,
} from '../utils/tutor'

interface Props {
  onStartToday: () => void
}

export function TutorTodayLearningCard({ onStartToday }: Props) {
  const { status, plan, error, retry } = useTodayPlan()
  const summaryReasons = visibleReasonLabels(plan?.summary_reason_codes)
  const previewEntries = (plan?.entries ?? []).slice(0, MAX_TODAY_PLAN_PREVIEW)

  return (
    <section style={styles.card} aria-labelledby="today-learning-heading">
      <h3 id="today-learning-heading" style={styles.heading}>
        今日の学習
      </h3>

      {status === 'loading' && (
        <p style={styles.msg} role="status">
          読み込み中...
        </p>
      )}

      {status === 'error' && (
        <div role="alert">
          <p style={styles.errorText}>{error}</p>
          <button type="button" style={styles.retryBtn} onClick={retry}>
            再試行
          </button>
        </div>
      )}

      {status === 'success' && plan && plan.total_count === 0 && (
        <div role="status">
          <p style={styles.emptyTitle}>今日は学習できる項目がありません</p>
          <p style={styles.emptyHint}>
            教材を追加するか、学習候補を採用すると、ここに今日の学習が表示されます
          </p>
          {plan.deferred_due_count > 0 && (
            <p style={styles.deferred}>
              あとで復習できる項目が {plan.deferred_due_count}件あります
            </p>
          )}
        </div>
      )}

      {status === 'success' && plan && plan.total_count > 0 && (
        <>
          <p style={styles.totalLine}>
            今日の問題{' '}
            <span style={styles.totalCount} data-testid="today-total-count">
              {plan.total_count}
            </span>
            問
          </p>
          <p style={styles.mixLine} data-testid="today-mix">
            復習 {plan.review_count} / 新規 {plan.new_count}
          </p>
          {plan.deferred_due_count > 0 && (
            <p style={styles.deferred}>
              あとで復習できる項目が {plan.deferred_due_count}件あります
            </p>
          )}
          {plan.explanation_summary && (
            <p style={styles.summary}>{plan.explanation_summary}</p>
          )}
          {summaryReasons.length > 0 && (
            <ul style={styles.reasonList} aria-label="今日の学習の理由">
              {summaryReasons.map(label => (
                <li key={label} style={styles.reasonItem}>
                  {label}
                </li>
              ))}
            </ul>
          )}
          {previewEntries.length > 0 && (
            <ul style={styles.previewList} aria-label="今日の学習の一部">
              {previewEntries.map(entry => (
                <PreviewRow key={`${entry.learning_item_id}-${entry.skill_direction}`} entry={entry} />
              ))}
            </ul>
          )}
          <button type="button" style={styles.startBtn} onClick={onStartToday}>
            学習を始める
          </button>
        </>
      )}
    </section>
  )
}

function PreviewRow({ entry }: { entry: TodayPlanEntryView }) {
  const reasons = visibleReasonLabels(entry.reason_codes)
  return (
    <li style={styles.previewItem}>
      <span style={styles.previewKind}>{todayActivityLabel(entry.activity_kind)}</span>
      <span lang="fr" style={styles.previewForm}>
        {entry.canonical_form}
      </span>
      {reasons.length > 0 && (
        <span style={styles.previewReason}>{reasons.join(' / ')}</span>
      )}
    </li>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    textAlign: 'left',
    padding: 20,
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    marginBottom: 16,
    border: '2px solid #1a56d6',
    boxSizing: 'border-box',
    width: '100%',
  },
  heading: {
    margin: '0 0 12px',
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  msg: {
    margin: 0,
    color: '#666',
    fontSize: 15,
  },
  errorText: {
    margin: '0 0 12px',
    color: '#444',
    fontSize: 15,
    lineHeight: 1.5,
  },
  emptyTitle: {
    margin: '0 0 8px',
    fontSize: 16,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  emptyHint: {
    margin: 0,
    fontSize: 14,
    color: '#666',
    lineHeight: 1.5,
  },
  totalLine: {
    margin: '0 0 8px',
    fontSize: 16,
    fontWeight: 600,
    color: '#1a1a2e',
  },
  totalCount: {
    fontSize: 32,
    fontWeight: 800,
    color: '#1a56d6',
    lineHeight: 1.1,
  },
  mixLine: {
    margin: '0 0 8px',
    fontSize: 16,
    fontWeight: 600,
    color: '#1a1a2e',
  },
  deferred: {
    margin: '0 0 8px',
    fontSize: 14,
    color: '#555',
    lineHeight: 1.4,
  },
  summary: {
    margin: '0 0 10px',
    fontSize: 14,
    color: '#444',
    lineHeight: 1.5,
  },
  reasonList: {
    listStyle: 'none',
    margin: '0 0 12px',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  reasonItem: {
    fontSize: 13,
    color: '#555',
    lineHeight: 1.4,
  },
  previewList: {
    listStyle: 'none',
    margin: '0 0 16px',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  previewItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: '8px 10px',
    background: '#f8fafc',
    borderRadius: 10,
  },
  previewKind: {
    fontSize: 12,
    fontWeight: 700,
    color: '#1a56d6',
  },
  previewForm: {
    fontSize: 15,
    fontWeight: 600,
    color: '#1a1a2e',
    overflowWrap: 'anywhere',
  },
  previewReason: {
    fontSize: 12,
    color: '#666',
    lineHeight: 1.4,
  },
  startBtn: {
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
  retryBtn: {
    fontSize: 16,
    fontWeight: 700,
    padding: '12px 0',
    minHeight: 48,
    borderRadius: 14,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
}

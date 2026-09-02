import { useReviewQueue } from '../hooks/useReviewQueue'

interface Props {
  onStartReview: () => void
}

export function TutorTodayReviewCard({ onStartReview }: Props) {
  const { status, summary, error, retry } = useReviewQueue()
  const dueCount = summary.total_due

  return (
    <section style={styles.card} aria-labelledby="today-review-heading">
      <h3 id="today-review-heading" style={styles.heading}>
        今日の復習
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

      {status === 'success' && dueCount === 0 && (
        <div role="status">
          <p style={styles.emptyTitle}>今すぐ復習する項目はありません</p>
          <p style={styles.emptyHint}>
            教材を追加するか、下の「学習する」から新しい項目を練習できます
          </p>
        </div>
      )}

      {status === 'success' && dueCount > 0 && (
        <>
          <p style={styles.dueLine}>
            復習待ち{' '}
            <span style={styles.dueCount} data-testid="due-count">
              {dueCount}
            </span>
            件
          </p>
          {summary.overdue_count > 0 && (
            <p style={styles.overdue}>期限を過ぎた復習 {summary.overdue_count}件</p>
          )}
          <p style={styles.directionSummary}>
            見て分かる練習 {summary.recognition_due}件 / 自分で言う練習{' '}
            {summary.production_due}件
          </p>
          <button type="button" style={styles.startBtn} onClick={onStartReview}>
            復習を始める
          </button>
        </>
      )}
    </section>
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
    border: '2px solid #e0e7ff',
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
  dueLine: {
    margin: '0 0 8px',
    fontSize: 16,
    fontWeight: 600,
    color: '#1a1a2e',
  },
  dueCount: {
    fontSize: 32,
    fontWeight: 800,
    color: '#1a56d6',
    lineHeight: 1.1,
  },
  overdue: {
    margin: '0 0 8px',
    fontSize: 14,
    color: '#555',
    lineHeight: 1.4,
  },
  directionSummary: {
    margin: '0 0 16px',
    fontSize: 13,
    color: '#666',
    lineHeight: 1.5,
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

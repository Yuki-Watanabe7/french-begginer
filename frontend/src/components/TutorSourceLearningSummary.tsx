import { useSourceLearningSummary } from '../hooks/useSourceLearningSummary'
import type { DirectionLearningSummary } from '../types'

interface Props {
  sourceId: string
}

function directionText(label: string, row: DirectionLearningSummary): string {
  if (row.attempt_count === 0) return `${label} 未学習`
  return `${label} ${row.correct_count}/${row.attempt_count}`
}

export function TutorSourceLearningSummary({ sourceId }: Props) {
  const { status, summary, error, retry } = useSourceLearningSummary(sourceId)
  const hasItems = summary != null && summary.accepted_item_count > 0

  return (
    <section style={styles.section} aria-labelledby="source-learning-heading">
      <h3 id="source-learning-heading" style={styles.heading}>
        学習状況
      </h3>

      {status === 'loading' && (
        <p style={styles.msg} role="status">
          学習状況を読み込み中...
        </p>
      )}

      {status === 'error' && (
        <div style={styles.errorBox} role="alert">
          <p style={styles.errorText}>{error}</p>
          <button type="button" style={styles.retryBtn} onClick={retry}>
            学習状況を再読み込み
          </button>
        </div>
      )}

      {status === 'success' && summary && !hasItems && (
        <p style={styles.empty} role="status">
          採用した学習項目はまだありません
        </p>
      )}

      {status === 'success' && summary && hasItems && (
        <>
          <p style={styles.caption}>
            この教材に結びついた項目の、いまの状態です。
          </p>
          <ul style={styles.stats} aria-label="学習状況の内訳">
            <li style={styles.stat} data-testid="source-learning-accepted">
              採用した項目 {summary.accepted_item_count}
            </li>
            <li style={styles.stat} data-testid="source-learning-started">
              学習開始済み {summary.started_item_count}
            </li>
            <li style={styles.stat} data-testid="source-learning-due">
              復習待ち {summary.due_direction_count}
            </li>
            <li style={styles.stat} data-testid="source-learning-known">
              既知/十分定着 {summary.mastered_or_known_count}
            </li>
          </ul>
          <ul style={styles.directions} aria-label="見て分かる練習と自分で言う練習">
            <li style={styles.stat}>
              {directionText('見て分かる', summary.recognition)}
            </li>
            <li style={styles.stat}>
              {directionText('自分で言う', summary.production)}
            </li>
          </ul>
          {summary.attempts > 0 && (
            <p style={styles.rate}>
              正答 {summary.correct_count}/{summary.attempts}
            </p>
          )}
        </>
      )}
    </section>
  )
}

const styles: Record<string, React.CSSProperties> = {
  section: {
    display: 'flex',
    flexDirection: 'column',
    width: '100%',
    maxWidth: '100%',
    minWidth: 0,
    boxSizing: 'border-box',
    margin: '4px 0 12px',
    padding: 16,
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    overflowWrap: 'anywhere',
  },
  heading: {
    margin: '0 0 8px',
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  caption: {
    margin: '0 0 10px',
    fontSize: 13,
    color: '#64748b',
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
  },
  stats: {
    listStyle: 'none',
    margin: 0,
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  directions: {
    listStyle: 'none',
    margin: '10px 0 0',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  stat: {
    margin: 0,
    fontSize: 15,
    color: '#1a1a2e',
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  rate: {
    margin: '10px 0 0',
    fontSize: 14,
    color: '#444',
    overflowWrap: 'anywhere',
  },
  empty: {
    margin: 0,
    fontSize: 14,
    color: '#555',
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
  },
  msg: {
    margin: 0,
    textAlign: 'center',
    color: '#666',
    fontSize: 15,
  },
  errorBox: {
    textAlign: 'center',
  },
  errorText: {
    margin: '0 0 12px',
    color: '#444',
    fontSize: 15,
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
  },
  retryBtn: {
    fontSize: 16,
    fontWeight: 700,
    padding: '12px 0',
    minHeight: 48,
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
}

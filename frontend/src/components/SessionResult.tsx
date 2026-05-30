import type { WrongAnswer } from '../types'

interface Props {
  correctCount: number
  wrongAnswers: WrongAnswer[]
  sessionTotal: number
  onRetry: () => void
  onReview: () => void
  onBackToSetup: () => void
}

export function SessionResult({ correctCount, wrongAnswers, sessionTotal, onRetry, onReview, onBackToSetup }: Props) {
  const wrongCount = wrongAnswers.length
  const accuracy = sessionTotal > 0 ? Math.round((correctCount / sessionTotal) * 100) : 0
  const accuracyColor = accuracy >= 80 ? '#059669' : accuracy >= 50 ? '#d97706' : '#dc2626'

  return (
    <div style={styles.card}>
      <h2 style={styles.heading}>セッション結果</h2>

      <div style={styles.accuracyBox}>
        <span style={{ ...styles.accuracyNum, color: accuracyColor }}>{accuracy}%</span>
        <span style={styles.accuracyLabel}>正答率</span>
      </div>

      <div style={styles.stats}>
        <div style={styles.statItem}>
          <span style={{ ...styles.statNum, color: '#059669' }}>{correctCount}</span>
          <span style={styles.statLabel}>正解</span>
        </div>
        <div style={styles.statItem}>
          <span style={{ ...styles.statNum, color: '#dc2626' }}>{wrongCount}</span>
          <span style={styles.statLabel}>不正解</span>
        </div>
        <div style={styles.statItem}>
          <span style={styles.statNum}>{sessionTotal}</span>
          <span style={styles.statLabel}>合計</span>
        </div>
      </div>

      <div style={styles.btnGroup}>
        <button style={styles.primaryBtn} onClick={onRetry}>もう一度挑戦</button>
        {wrongCount > 0 && (
          <button style={styles.secondaryBtn} onClick={onReview}>
            間違えた問題だけ復習（{wrongCount}問）
          </button>
        )}
        <button style={styles.backBtn} onClick={onBackToSetup}>モード選択に戻る</button>
      </div>

      {wrongCount > 0 && (
        <div style={styles.wrongSection}>
          <h3 style={styles.wrongHeading}>間違えた問題</h3>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>動詞</th>
                  <th style={styles.th}>時制</th>
                  <th style={styles.th}>人称</th>
                  <th style={styles.th}>正解</th>
                  <th style={styles.th}>回答</th>
                </tr>
              </thead>
              <tbody>
                {wrongAnswers.map((w, i) => (
                  <tr key={i} style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}>
                    <td style={styles.td}>{w.verb}</td>
                    <td style={styles.td}>{w.tense}</td>
                    <td style={styles.td}>{w.pronoun}</td>
                    <td style={{ ...styles.td, color: '#059669', fontWeight: 600 }}>{w.correctAnswer}</td>
                    <td style={{ ...styles.td, color: '#dc2626' }}>{w.userAnswer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: '#fff',
    borderRadius: 16,
    padding: '28px 24px',
    boxShadow: '0 4px 24px rgba(0,0,0,0.10)',
    display: 'flex',
    flexDirection: 'column',
    gap: 24,
  },
  heading: {
    margin: 0,
    fontSize: 22,
    fontWeight: 700,
    color: '#1a1a2e',
    textAlign: 'center',
  },
  accuracyBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 4,
  },
  accuracyNum: {
    fontSize: 64,
    fontWeight: 800,
    lineHeight: 1,
  },
  accuracyLabel: {
    fontSize: 16,
    color: '#666',
  },
  stats: {
    display: 'flex',
    justifyContent: 'space-around',
    background: '#f8fafc',
    borderRadius: 12,
    padding: '16px 8px',
  },
  statItem: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 4,
  },
  statNum: {
    fontSize: 28,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  statLabel: {
    fontSize: 13,
    color: '#888',
  },
  btnGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  primaryBtn: {
    fontSize: 18,
    fontWeight: 700,
    padding: '14px',
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  secondaryBtn: {
    fontSize: 16,
    fontWeight: 600,
    padding: '12px',
    borderRadius: 12,
    border: '2px solid #1a56d6',
    background: '#fff',
    color: '#1a56d6',
    cursor: 'pointer',
    width: '100%',
  },
  backBtn: {
    fontSize: 15,
    fontWeight: 500,
    padding: '10px',
    borderRadius: 12,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#666',
    cursor: 'pointer',
    width: '100%',
  },
  wrongSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  wrongHeading: {
    margin: 0,
    fontSize: 16,
    fontWeight: 600,
    color: '#333',
  },
  tableWrapper: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 14,
  },
  th: {
    padding: '8px 10px',
    background: '#f0f4ff',
    color: '#1a56d6',
    fontWeight: 600,
    textAlign: 'left',
    whiteSpace: 'nowrap',
  },
  td: {
    padding: '8px 10px',
    color: '#333',
    whiteSpace: 'nowrap',
  },
  rowEven: {
    background: '#fff',
  },
  rowOdd: {
    background: '#f8fafc',
  },
}

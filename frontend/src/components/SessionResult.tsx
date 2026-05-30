import type { WrongAnswer } from '../types'

interface Props {
  correctCount: number
  sessionTotal: number
  wrongAnswers: WrongAnswer[]
  onNewSession: () => void
  onReview: () => void
}

export function SessionResult({ correctCount, sessionTotal, wrongAnswers, onNewSession, onReview }: Props) {
  const incorrectCount = sessionTotal - correctCount
  const accuracy = Math.round((correctCount / sessionTotal) * 100)

  const scoreColor = accuracy >= 80 ? '#059669' : accuracy >= 50 ? '#d97706' : '#dc2626'

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h2 style={styles.title}>セッション結果</h2>

        <div style={{ ...styles.scoreBig, color: scoreColor }}>
          {accuracy}<span style={styles.percent}>%</span>
        </div>

        <div style={styles.statsRow}>
          <div style={styles.statBox}>
            <div style={styles.statNum}>{correctCount}</div>
            <div style={styles.statLabel}>正解</div>
          </div>
          <div style={styles.statDivider} />
          <div style={styles.statBox}>
            <div style={{ ...styles.statNum, color: incorrectCount > 0 ? '#dc2626' : '#333' }}>{incorrectCount}</div>
            <div style={styles.statLabel}>不正解</div>
          </div>
          <div style={styles.statDivider} />
          <div style={styles.statBox}>
            <div style={styles.statNum}>{sessionTotal}</div>
            <div style={styles.statLabel}>合計</div>
          </div>
        </div>

        <div style={styles.btnGroup}>
          <button style={styles.primaryBtn} onClick={onNewSession}>
            もう一度挑戦
          </button>
          {wrongAnswers.length > 0 && (
            <button style={styles.secondaryBtn} onClick={onReview}>
              間違えた問題だけ復習（{wrongAnswers.length}問）
            </button>
          )}
        </div>
      </div>

      {wrongAnswers.length > 0 && (
        <div style={styles.wrongCard}>
          <h3 style={styles.wrongTitle}>間違えた問題一覧</h3>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>動詞</th>
                  <th style={styles.th}>人称</th>
                  <th style={styles.th}>正解</th>
                  <th style={styles.th}>あなたの回答</th>
                </tr>
              </thead>
              <tbody>
                {wrongAnswers.map((w, i) => (
                  <tr key={i} style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}>
                    <td style={styles.td}>
                      <div style={styles.verbCell}>{w.verb}</div>
                      <div style={styles.tenseCell}>{w.tense}</div>
                    </td>
                    <td style={styles.td}>{w.pronoun}</td>
                    <td style={{ ...styles.td, ...styles.correctCell }}>{w.correctAnswer}</td>
                    <td style={{ ...styles.td, ...styles.wrongCell }}>{w.userAnswer}</td>
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
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  card: {
    background: '#fff',
    borderRadius: 16,
    padding: '28px 24px',
    boxShadow: '0 4px 24px rgba(0,0,0,0.10)',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
    alignItems: 'center',
  },
  title: {
    margin: 0,
    fontSize: 20,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  scoreBig: {
    fontSize: 72,
    fontWeight: 800,
    lineHeight: 1,
  },
  percent: {
    fontSize: 32,
    fontWeight: 700,
  },
  statsRow: {
    display: 'flex',
    gap: 0,
    width: '100%',
    background: '#f8faff',
    borderRadius: 12,
    overflow: 'hidden',
  },
  statBox: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '16px 8px',
    gap: 4,
  },
  statNum: {
    fontSize: 28,
    fontWeight: 700,
    color: '#333',
  },
  statLabel: {
    fontSize: 13,
    color: '#666',
    fontWeight: 500,
  },
  statDivider: {
    width: 1,
    background: '#e0e7f0',
    margin: '12px 0',
  },
  btnGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    width: '100%',
  },
  primaryBtn: {
    fontSize: 17,
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
    padding: '13px',
    borderRadius: 12,
    border: '2px solid #1a56d6',
    background: '#fff',
    color: '#1a56d6',
    cursor: 'pointer',
    width: '100%',
  },
  wrongCard: {
    background: '#fff',
    borderRadius: 16,
    padding: '24px',
    boxShadow: '0 4px 24px rgba(0,0,0,0.10)',
  },
  wrongTitle: {
    margin: '0 0 16px',
    fontSize: 17,
    fontWeight: 700,
    color: '#1a1a2e',
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
    textAlign: 'left',
    fontSize: 12,
    fontWeight: 600,
    color: '#666',
    borderBottom: '2px solid #e8edf4',
    whiteSpace: 'nowrap',
  },
  td: {
    padding: '10px',
    verticalAlign: 'top',
    borderBottom: '1px solid #f0f4ff',
  },
  rowEven: {
    background: '#fff',
  },
  rowOdd: {
    background: '#fafbff',
  },
  verbCell: {
    fontWeight: 600,
    color: '#1a1a2e',
  },
  tenseCell: {
    fontSize: 11,
    color: '#888',
    marginTop: 2,
  },
  correctCell: {
    color: '#059669',
    fontWeight: 600,
  },
  wrongCell: {
    color: '#dc2626',
    fontWeight: 600,
  },
}

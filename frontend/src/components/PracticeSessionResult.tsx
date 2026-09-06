import type { PracticeWrongAnswer, TutorSessionKind } from '../types'
import { EXERCISE_TYPE_LABELS } from '../utils/tutor'

interface Props {
  correctCount: number
  wrongAnswers: PracticeWrongAnswer[]
  sessionTotal: number
  variant?: TutorSessionKind
  remainingDue?: number | null
  reviewCount?: number
  newCount?: number
  onRetry: () => void
  onBack: () => void
}

export function PracticeSessionResult({
  correctCount,
  wrongAnswers,
  sessionTotal,
  variant = 'practice',
  remainingDue = null,
  reviewCount,
  newCount,
  onRetry,
  onBack,
}: Props) {
  const incorrectCount = wrongAnswers.length
  const accuracy =
    sessionTotal > 0 ? Math.round((correctCount / sessionTotal) * 100) : 0
  const accuracyColor = accuracy >= 80 ? '#059669' : accuracy >= 50 ? '#d97706' : '#dc2626'
  const isReview = variant === 'review'
  const isToday = variant === 'today'
  const showRetry = !isReview || remainingDue === null || remainingDue > 0
  const heading = isToday ? '今日の学習' : isReview ? '復習完了' : 'セッション結果'
  const backLabel = isReview || isToday ? '教材一覧へ戻る' : '戻る'
  const retryLabel = isToday
    ? 'もう一度学習する'
    : isReview
      ? 'もう一度復習する'
      : 'もう一度挑戦'

  return (
    <div style={styles.card}>
      <h2 style={styles.heading}>{heading}</h2>
      {isReview && (
        <p style={styles.completeMsg}>今日の復習を終えました</p>
      )}
      {isToday && (
        <p style={styles.completeMsg}>今日の学習を終えました</p>
      )}
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
          <span style={{ ...styles.statNum, color: incorrectCount > 0 ? '#dc2626' : '#888' }}>
            {incorrectCount}
          </span>
          <span style={styles.statLabel}>不正解</span>
        </div>
        <div style={styles.statItem}>
          <span style={styles.statNum}>{sessionTotal}</span>
          <span style={styles.statLabel}>合計</span>
        </div>
      </div>
      {isToday && reviewCount != null && newCount != null && (
        <p style={styles.mixLine} data-testid="today-result-mix">
          復習 {reviewCount}件 / 新規 {newCount}件
        </p>
      )}
      {isReview && remainingDue != null && remainingDue > 0 && (
        <p style={styles.remaining}>まだ残っている復習は {remainingDue}件です</p>
      )}
      {isToday && remainingDue != null && remainingDue > 0 && (
        <p style={styles.remaining}>あとで復習できる項目が {remainingDue}件あります</p>
      )}
      <div style={styles.btnGroup}>
        {showRetry && (
          <button type="button" style={styles.primaryBtn} onClick={onRetry}>
            {retryLabel}
          </button>
        )}
        <button type="button" style={styles.backBtn} onClick={onBack}>
          {backLabel}
        </button>
      </div>
      {wrongAnswers.length > 0 && (
        <div style={styles.wrongSection}>
          <h3 style={styles.wrongHeading}>誤答した問題</h3>
          <ul style={styles.wrongList}>
            {wrongAnswers.map((row, index) => (
              <li key={`${row.exerciseType}-${index}`} style={styles.wrongItem}>
                <span style={styles.wrongType}>{EXERCISE_TYPE_LABELS[row.exerciseType]}</span>
                <span style={styles.wrongPrompt}>{row.prompt}</span>
                <span style={styles.wrongPair}>
                  正解: <strong>{row.correctAnswer}</strong>
                </span>
                <span style={styles.wrongGiven}>回答: {row.userAnswer}</span>
              </li>
            ))}
          </ul>
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
    width: '100%',
    boxSizing: 'border-box',
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
  completeMsg: {
    margin: 0,
    textAlign: 'center',
    fontSize: 15,
    color: '#444',
    lineHeight: 1.5,
  },
  mixLine: {
    margin: 0,
    textAlign: 'center',
    fontSize: 15,
    color: '#1a1a2e',
    lineHeight: 1.5,
  },
  remaining: {
    margin: 0,
    textAlign: 'center',
    fontSize: 15,
    color: '#1a1a2e',
    lineHeight: 1.5,
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
    minHeight: 48,
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  backBtn: {
    fontSize: 15,
    fontWeight: 500,
    padding: '10px',
    minHeight: 44,
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
  wrongList: {
    listStyle: 'none',
    margin: 0,
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  wrongItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    background: '#f8fafc',
    borderRadius: 12,
    padding: '12px 14px',
  },
  wrongType: {
    fontSize: 12,
    fontWeight: 700,
    color: '#1a56d6',
  },
  wrongPrompt: {
    fontSize: 14,
    color: '#1a1a2e',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
  wrongPair: {
    fontSize: 14,
    color: '#059669',
    overflowWrap: 'anywhere',
  },
  wrongGiven: {
    fontSize: 14,
    color: '#dc2626',
    overflowWrap: 'anywhere',
  },
}

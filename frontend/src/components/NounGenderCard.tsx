import { useTTS } from '../hooks/useTTS'
import type { NounGender, NounGenderAnswerResult, NounGenderQuestion } from '../types'

interface Props {
  question: NounGenderQuestion
  result: NounGenderAnswerResult | null
  onAnswer: (gender: NounGender) => void
  onNext: () => void
  questionNum: number
  sessionTotal: number
  isReviewPhase: boolean
  nextLabel: string
}

function choiceBtnStyle(
  gender: NounGender,
  result: NounGenderAnswerResult | null,
): React.CSSProperties {
  if (!result) return styles.choiceBtn
  if (result.given === gender) {
    return { ...styles.choiceBtn, ...(result.correct ? styles.choiceBtnCorrect : styles.choiceBtnWrong) }
  }
  if (!result.correct && result.expected === gender) {
    return { ...styles.choiceBtn, ...styles.choiceBtnHint }
  }
  return { ...styles.choiceBtn, opacity: 0.4 }
}

export function NounGenderCard({
  question,
  result,
  onAnswer,
  onNext,
  questionNum,
  sessionTotal,
  isReviewPhase,
  nextLabel,
}: Props) {
  const answered = !!result
  const { play, isLoading: ttsLoading } = useTTS()
  const ttsText = `${question.article_indefinite} ${question.noun}`

  return (
    <div style={styles.card}>
      <div style={styles.meta}>
        <span style={isReviewPhase ? styles.reviewBadge : styles.badge}>
          {isReviewPhase ? '復習' : '名詞の性'}
        </span>
        <span style={styles.progress}>
          {isReviewPhase ? '復習中' : `${questionNum} / ${sessionTotal}`}
        </span>
      </div>

      <div style={styles.nounRow}>
        <div style={styles.nounWithTts}>
          <span style={styles.noun}>{question.noun}</span>
          <button
            style={styles.ttsBtn}
            onClick={() => play(ttsText)}
            disabled={ttsLoading}
            aria-label={`${ttsText}を読み上げる`}
            title={ttsText}
          >
            {ttsLoading ? '…' : '🔊'}
          </button>
        </div>
        {question.meaning_ja && (
          <span style={styles.meaning}>{question.meaning_ja}</span>
        )}
      </div>

      <p style={styles.prompt}>この名詞の性は？</p>

      <div style={styles.choiceRow}>
        <button
          style={choiceBtnStyle('masculine', result)}
          onClick={() => { if (!answered) onAnswer('masculine') }}
          disabled={answered}
        >
          <span style={styles.choiceMain}>男性名詞</span>
          <span style={styles.choiceSub}>le / un</span>
        </button>
        <button
          style={choiceBtnStyle('feminine', result)}
          onClick={() => { if (!answered) onAnswer('feminine') }}
          disabled={answered}
        >
          <span style={styles.choiceMain}>女性名詞</span>
          <span style={styles.choiceSub}>la / une</span>
        </button>
      </div>

      {result && (
        <div style={result.correct ? styles.correct : styles.incorrect}>
          <div style={styles.resultLabel}>{result.correct ? '✓ 正解' : '✗ 不正解'}</div>
          {!result.correct && (
            <div style={styles.answer}>
              正解: <strong>{result.expected === 'masculine' ? '男性名詞' : '女性名詞'}</strong>
            </div>
          )}
          <button style={styles.nextBtn} onClick={onNext}>
            {nextLabel}
          </button>
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
    gap: 20,
  },
  meta: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  badge: {
    background: '#e8f0fe',
    color: '#1a56d6',
    borderRadius: 99,
    padding: '4px 12px',
    fontSize: 14,
    fontWeight: 600,
  },
  reviewBadge: {
    background: '#fef3c7',
    color: '#d97706',
    borderRadius: 99,
    padding: '4px 12px',
    fontSize: 14,
    fontWeight: 600,
  },
  progress: {
    fontSize: 14,
    color: '#888',
    fontWeight: 500,
  },
  nounRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    alignItems: 'center',
    textAlign: 'center',
  },
  nounWithTts: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  noun: {
    fontSize: 44,
    fontWeight: 700,
    color: '#1a1a2e',
    letterSpacing: 2,
  },
  ttsBtn: {
    background: 'none',
    border: '1.5px solid #c0c8d8',
    borderRadius: 8,
    padding: '4px 8px',
    fontSize: 20,
    cursor: 'pointer',
    color: '#555',
    lineHeight: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  meaning: {
    fontSize: 16,
    color: '#888',
  },
  prompt: {
    margin: 0,
    textAlign: 'center',
    fontSize: 15,
    color: '#666',
  },
  choiceRow: {
    display: 'flex',
    gap: 12,
  },
  choiceBtn: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: '20px 12px',
    minHeight: 80,
    borderRadius: 14,
    border: '2px solid #1a56d6',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    transition: 'opacity 0.1s',
  },
  choiceBtnCorrect: {
    background: '#059669',
    border: '2px solid #047857',
    opacity: 1,
  },
  choiceBtnWrong: {
    background: '#dc2626',
    border: '2px solid #b91c1c',
    opacity: 1,
  },
  choiceBtnHint: {
    background: '#d1fae5',
    border: '2px solid #059669',
    color: '#065f46',
    opacity: 1,
  },
  choiceMain: {
    fontSize: 17,
    fontWeight: 700,
  },
  choiceSub: {
    fontSize: 13,
    opacity: 0.85,
  },
  correct: {
    background: '#d1fae5',
    borderRadius: 12,
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    alignItems: 'center',
  },
  incorrect: {
    background: '#fee2e2',
    borderRadius: 12,
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    alignItems: 'center',
  },
  resultLabel: {
    fontSize: 22,
    fontWeight: 700,
  },
  answer: {
    fontSize: 18,
    color: '#333',
  },
  nextBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '12px 24px',
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
}

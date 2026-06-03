import { useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import { useTTS } from '../hooks/useTTS'
import type { AnswerResult, Question } from '../types'

interface Props {
  question: Question
  input: string
  result: AnswerResult | null
  inputRef: React.RefObject<HTMLInputElement>
  onInputChange: (v: string) => void
  onSubmit: () => void
  onNext: () => void
  questionNum: number
  sessionTotal: number
  isReviewPhase: boolean
  nextLabel: string
}

export function QuizCard({
  question,
  input,
  result,
  inputRef,
  onInputChange,
  onSubmit,
  onNext,
  questionNum,
  sessionTotal,
  isReviewPhase,
  nextLabel,
}: Props) {
  const { play, isLoading: ttsLoading, error: ttsError, clearError: ttsClearError } = useTTS()

  useEffect(() => {
    ttsClearError()
  }, [question, ttsClearError])

  useEffect(() => {
    if (!result) return
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.isComposing) {
        onNext()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [result, onNext])

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !result) {
      onSubmit()
    }
  }

  return (
    <div style={styles.card}>
      <div style={styles.meta}>
        <span style={isReviewPhase ? styles.reviewBadge : styles.badge}>
          {isReviewPhase ? '復習' : question.tense}
        </span>
        <span style={styles.progress}>
          {isReviewPhase ? '復習中' : `${questionNum} / ${sessionTotal}`}
        </span>
      </div>

      <div style={styles.verbRow}>
        <span style={styles.pronoun}>{question.pronoun}</span>
        <span style={styles.verb}>{question.verb}</span>
      </div>

      <input
        ref={inputRef}
        style={styles.input}
        type="text"
        value={input}
        onChange={e => onInputChange(e.target.value)}
        onKeyDown={handleKey}
        placeholder="活用形を入力..."
        disabled={!!result}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="none"
        spellCheck={false}
      />

      {!result && (
        <button style={styles.primaryBtn} onClick={onSubmit} disabled={input.trim() === ''}>
          判定する
        </button>
      )}

      {result && (
        <div style={result.correct ? styles.correct : styles.incorrect}>
          <div style={styles.resultLabel}>{result.correct ? '✓ 正解' : '✗ 不正解'}</div>
          <div style={styles.answerRow}>
            {!result.correct && (
              <div style={styles.answer}>正解: <strong>{result.expected}</strong></div>
            )}
            <button
              style={styles.ttsBtn}
              onClick={() => play(`${question.pronoun} ${result.expected}`)}
              disabled={ttsLoading}
              aria-label={`${question.pronoun} ${result.expected}を読み上げる`}
              title={`${question.pronoun} ${result.expected}`}
            >
              {ttsLoading ? '…' : '🔊'}
            </button>
          </div>
          {ttsError && (
            <span style={styles.ttsError} role="alert">{ttsError}</span>
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
  verbRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  pronoun: {
    fontSize: 18,
    color: '#555',
    fontWeight: 500,
  },
  verb: {
    fontSize: 36,
    fontWeight: 700,
    color: '#1a1a2e',
    letterSpacing: 1,
  },
  input: {
    fontSize: 24,
    padding: '14px 16px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    transition: 'border-color 0.15s',
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
  answerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  answer: {
    fontSize: 18,
    color: '#333',
  },
  ttsBtn: {
    background: 'none',
    border: '1.5px solid #c0c8d8',
    borderRadius: 8,
    padding: '4px 8px',
    fontSize: 18,
    cursor: 'pointer',
    color: '#555',
    lineHeight: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  ttsError: {
    fontSize: 12,
    color: '#dc2626',
    textAlign: 'center',
    wordBreak: 'break-word',
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

import type { KeyboardEvent } from 'react'
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
}

export function QuizCard({ question, input, result, inputRef, onInputChange, onSubmit, onNext, questionNum, sessionTotal }: Props) {
  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      result ? onNext() : onSubmit()
    }
  }

  const isLast = questionNum >= sessionTotal

  return (
    <div style={styles.card}>
      <div style={styles.meta}>
        <span style={styles.badge}>{question.tense}</span>
        <span style={styles.progress}>{questionNum} / {sessionTotal}</span>
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
          {!result.correct && (
            <div style={styles.answer}>正解: <strong>{result.expected}</strong></div>
          )}
          <button style={styles.nextBtn} onClick={onNext}>
            {isLast ? '結果を見る →' : '次の問題 →'}
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

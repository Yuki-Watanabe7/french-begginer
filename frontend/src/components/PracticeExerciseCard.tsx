import { useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import { useTTS } from '../hooks/useTTS'
import type { ExerciseFeedback, ExerciseView, LearningItem } from '../types'
import {
  EXERCISE_TYPE_LABELS,
  practiceFrenchTtsTargets,
} from '../utils/tutor'
import { KnownItemControl } from './KnownItemControl'
import { PracticeReconstructionBoard } from './PracticeReconstructionBoard'

interface Props {
  exercise: ExerciseView
  item?: LearningItem
  input: string
  reconstruction: number[]
  feedback: ExerciseFeedback | null
  submitting: boolean
  submitError: string | null
  inputRef: React.RefObject<HTMLInputElement>
  questionNum: number
  sessionTotal: number
  activityLabel?: string | null
  reasonLabels?: string[]
  onInputChange: (value: string) => void
  onReconstructionChange: (indices: number[]) => void
  onSubmit: () => void
  onChoice: (option: string) => void
  onNext: () => void
  knownAction?: {
    explicitKnown: boolean
    busy: boolean
    error: string | null
    onMark: () => void
    onUndo: () => void
  } | null
  onSkipUnanswered?: () => void
}

function choiceStyle(
  option: string,
  feedback: ExerciseFeedback | null,
): React.CSSProperties {
  if (!feedback) return styles.choiceBtn
  const given = typeof feedback.given === 'string' ? feedback.given : ''
  if (given === option) {
    return {
      ...styles.choiceBtn,
      ...(feedback.correct ? styles.choiceCorrect : styles.choiceWrong),
    }
  }
  if (!feedback.correct && feedback.correct_answer === option) {
    return { ...styles.choiceBtn, ...styles.choiceHint }
  }
  return { ...styles.choiceBtn, opacity: 0.45 }
}

export function PracticeExerciseCard({
  exercise,
  item,
  input,
  reconstruction,
  feedback,
  submitting,
  submitError,
  inputRef,
  questionNum,
  sessionTotal,
  activityLabel = null,
  reasonLabels = [],
  onInputChange,
  onReconstructionChange,
  onSubmit,
  onChoice,
  onNext,
  knownAction = null,
  onSkipUnanswered,
}: Props) {
  const answered = feedback !== null
  const suppressAnswer = Boolean(knownAction?.explicitKnown) && !answered
  const { play, isLoading: ttsLoading, error: ttsError, clearError: ttsClearError } = useTTS()
  const ttsTargets = practiceFrenchTtsTargets(
    exercise,
    item,
    feedback?.correct_answer ?? null,
  )
  const nextLabel =
    questionNum >= sessionTotal ? '結果を見る →' : '次の問題 →'
  const canSubmitText = input.trim() !== '' && !submitting
  const options = exercise.options ?? []
  const canSubmitReconstruction =
    reconstruction.length === options.length && options.length > 0 && !submitting

  useEffect(() => {
    ttsClearError()
  }, [exercise, ttsClearError])

  useEffect(() => {
    if (!feedback) return
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.isComposing) {
        onNext()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [feedback, onNext])

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing && !answered && canSubmitText) {
      onSubmit()
    }
  }

  return (
    <div style={styles.card}>
      <div style={styles.meta}>
        <div style={styles.badgeRow}>
          <span style={styles.badge}>{EXERCISE_TYPE_LABELS[exercise.exercise_type]}</span>
          {activityLabel && (
            <span style={styles.activityBadge}>{activityLabel}</span>
          )}
        </div>
        <span style={styles.progress}>
          {questionNum} / {sessionTotal}
        </span>
      </div>
      {reasonLabels.length > 0 && (
        <details style={styles.reasonDetails}>
          <summary style={styles.reasonSummary}>なぜ出たか</summary>
          <ul style={styles.reasonList}>
            {reasonLabels.map(label => (
              <li key={label} style={styles.reasonItem}>
                {label}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p lang="fr" style={styles.prompt}>
        {exercise.prompt}
      </p>

      {ttsTargets.length > 0 && (
        <div style={styles.ttsRow}>
          {ttsTargets.map(text => (
            <button
              key={text}
              type="button"
              style={styles.ttsBtn}
              onClick={() => {
                void play(text)
              }}
              disabled={ttsLoading}
              aria-label={`${text}を読み上げる`}
              title={text}
            >
              {ttsLoading ? '…' : '🔊'} {text}
            </button>
          ))}
        </div>
      )}
      {ttsError && (
        <span style={styles.ttsError} role="alert">
          {ttsError}
        </span>
      )}

      {exercise.response_kind === 'choice' && !suppressAnswer && (
        <>
          <div style={styles.choiceList} role="group" aria-label="選択肢">
            {options.map(option => (
              <button
                key={option}
                type="button"
                style={choiceStyle(option, feedback)}
                disabled={answered || submitting}
                onClick={() => {
                  if (!answered) onChoice(option)
                }}
              >
                {option}
              </button>
            ))}
          </div>
          {submitting && (
            <p style={styles.submitting} role="status">
              判定中...
            </p>
          )}
        </>
      )}

      {exercise.response_kind === 'text' && !suppressAnswer && (
        <input
          ref={inputRef}
          style={styles.input}
          type="text"
          value={input}
          onChange={e => onInputChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="回答を入力..."
          disabled={answered || submitting}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="none"
          spellCheck={false}
        />
      )}

      {exercise.response_kind === 'reconstruction' && !suppressAnswer && (
        <PracticeReconstructionBoard
          options={options}
          selectedIndices={reconstruction}
          disabled={answered || submitting}
          onChange={onReconstructionChange}
        />
      )}

      {exercise.response_kind === 'text' && !answered && !suppressAnswer && (
        <button
          type="button"
          style={styles.primaryBtn}
          onClick={onSubmit}
          disabled={!canSubmitText}
        >
          {submitting ? '判定中...' : '判定する'}
        </button>
      )}

      {exercise.response_kind === 'reconstruction' && !answered && !suppressAnswer && (
        <button
          type="button"
          style={styles.primaryBtn}
          onClick={onSubmit}
          disabled={!canSubmitReconstruction}
        >
          {submitting ? '判定中...' : '判定する'}
        </button>
      )}

      {submitError && (
        <p style={styles.submitError} role="alert">
          {submitError}
        </p>
      )}

      {feedback && (
        <div style={feedback.correct ? styles.correct : styles.incorrect}>
          <div style={styles.resultLabel}>
            {feedback.correct ? '✓ 正解' : '✗ 不正解'}
          </div>
          <div style={styles.answer}>
            正解: <strong>{feedback.correct_answer}</strong>
          </div>
          {(feedback.canonical_form || feedback.meaning_ja) && (
            <div style={styles.remember}>
              {feedback.canonical_form && (
                <div lang="fr" style={styles.canonical}>
                  {feedback.canonical_form}
                </div>
              )}
              {feedback.meaning_ja && (
                <div style={styles.meaning}>{feedback.meaning_ja}</div>
              )}
            </div>
          )}
          {feedback.explanation_ja && (
            <p style={styles.explanation}>{feedback.explanation_ja}</p>
          )}
          {feedback.source_context && (
            <blockquote lang="fr" style={styles.evidence}>
              {feedback.source_context}
            </blockquote>
          )}
          <button type="button" style={styles.nextBtn} onClick={onNext}>
            {nextLabel}
          </button>
        </div>
      )}
      {knownAction && (
        <KnownItemControl
          key={`${exercise.learning_item_id}:${exercise.exercise_type}`}
          explicitKnown={knownAction.explicitKnown}
          busy={knownAction.busy}
          error={knownAction.error}
          onMark={knownAction.onMark}
          onUndo={knownAction.onUndo}
        />
      )}
      {knownAction?.explicitKnown && !answered && onSkipUnanswered && (
        <button type="button" style={styles.nextBtn} onClick={onSkipUnanswered}>
          {nextLabel}
        </button>
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
    gap: 16,
    width: '100%',
    boxSizing: 'border-box',
  },
  meta: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  badgeRow: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 6,
  },
  badge: {
    background: '#e8f0fe',
    color: '#1a56d6',
    borderRadius: 99,
    padding: '4px 12px',
    fontSize: 14,
    fontWeight: 600,
  },
  activityBadge: {
    background: '#f1f5f9',
    color: '#475569',
    borderRadius: 99,
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
  },
  reasonDetails: {
    margin: 0,
    fontSize: 13,
    color: '#555',
  },
  reasonSummary: {
    cursor: 'pointer',
    fontWeight: 600,
    color: '#64748b',
  },
  reasonList: {
    listStyle: 'none',
    margin: '6px 0 0',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  reasonItem: {
    lineHeight: 1.4,
  },
  progress: {
    fontSize: 14,
    color: '#888',
    fontWeight: 500,
  },
  prompt: {
    margin: 0,
    fontSize: 18,
    fontWeight: 600,
    color: '#1a1a2e',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  ttsRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
  },
  ttsBtn: {
    background: '#fff',
    border: '1.5px solid #c0c8d8',
    borderRadius: 10,
    padding: '8px 10px',
    minHeight: 44,
    fontSize: 14,
    cursor: 'pointer',
    color: '#334155',
    overflowWrap: 'anywhere',
    maxWidth: '100%',
  },
  ttsError: {
    fontSize: 12,
    color: '#dc2626',
    wordBreak: 'break-word',
  },
  choiceList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    width: '100%',
  },
  choiceBtn: {
    fontSize: 16,
    fontWeight: 700,
    minHeight: 48,
    padding: '12px 16px',
    borderRadius: 12,
    border: '2px solid #e0e7ff',
    background: '#fff',
    color: '#1a1a2e',
    cursor: 'pointer',
    textAlign: 'left',
    width: '100%',
    overflowWrap: 'anywhere',
  },
  choiceCorrect: {
    border: '2px solid #059669',
    background: '#d1fae5',
  },
  choiceWrong: {
    border: '2px solid #dc2626',
    background: '#fee2e2',
  },
  choiceHint: {
    border: '2px solid #059669',
  },
  input: {
    fontSize: 20,
    padding: '14px 16px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
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
  submitError: {
    margin: 0,
    color: '#b91c1c',
    fontSize: 14,
    background: '#fee2e2',
    borderRadius: 10,
    padding: '10px 12px',
    lineHeight: 1.5,
  },
  submitting: {
    margin: 0,
    textAlign: 'center',
    color: '#64748b',
    fontSize: 14,
  },
  correct: {
    background: '#d1fae5',
    borderRadius: 12,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  incorrect: {
    background: '#fee2e2',
    borderRadius: 12,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  resultLabel: {
    fontSize: 22,
    fontWeight: 700,
    textAlign: 'center',
  },
  answer: {
    fontSize: 16,
    color: '#333',
    textAlign: 'center',
    overflowWrap: 'anywhere',
  },
  remember: {
    background: 'rgba(255,255,255,0.7)',
    borderRadius: 10,
    padding: '10px 12px',
    textAlign: 'center',
  },
  canonical: {
    fontSize: 18,
    fontWeight: 700,
    overflowWrap: 'anywhere',
  },
  meaning: {
    fontSize: 15,
    color: '#334155',
    marginTop: 4,
    overflowWrap: 'anywhere',
  },
  explanation: {
    margin: 0,
    fontSize: 14,
    color: '#334155',
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
  },
  evidence: {
    margin: 0,
    fontSize: 14,
    lineHeight: 1.6,
    color: '#334155',
    background: 'rgba(255,255,255,0.7)',
    borderRadius: 10,
    padding: '10px 12px',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  nextBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '12px 24px',
    minHeight: 48,
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
}

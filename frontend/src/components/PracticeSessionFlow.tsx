import { useEffect, useState } from 'react'
import { fetchReviewQueue } from '../api/tutor'
import { PracticeExerciseCard } from './PracticeExerciseCard'
import { PracticeSessionResult } from './PracticeSessionResult'
import { usePracticeSession } from '../hooks/usePracticeSession'
import type { TutorSessionKind } from '../types'
import { todayActivityLabel, visibleEntryReasons } from '../utils/tutor'

interface Props {
  sourceId?: string
  questionCount: number
  kind?: TutorSessionKind
  onExit: () => void
}

export function PracticeSessionFlow({
  sourceId,
  questionCount,
  kind = 'practice',
  onExit,
}: Props) {
  const {
    state,
    current,
    currentItem,
    currentTodayEntry,
    inputRef,
    submit,
    submitChoice,
    nextQuestion,
    setInput,
    setReconstruction,
    retry,
  } = usePracticeSession(sourceId, questionCount, kind)
  const [remainingDue, setRemainingDue] = useState<number | null>(null)

  useEffect(() => {
    if (
      (kind !== 'review' && kind !== 'today') ||
      state.phase !== 'session-result'
    ) {
      setRemainingDue(null)
      return
    }
    let cancelled = false
    void fetchReviewQueue()
      .then(queue => {
        if (!cancelled) setRemainingDue(queue.summary.total_due)
      })
      .catch(() => {
        // 完了後の queue 再取得失敗は学習結果自体を失敗扱いしない。
      })
    return () => {
      cancelled = true
    }
  }, [kind, state.phase])

  if (state.phase === 'loading') {
    return (
      <p style={styles.msg} role="status">
        読み込み中...
      </p>
    )
  }

  if (state.phase === 'error') {
    return (
      <div style={styles.errorBox} role="alert">
        <p style={styles.errorText}>{state.error}</p>
        <button type="button" style={styles.primaryBtn} onClick={() => { void retry() }}>
          再試行
        </button>
        <button type="button" style={styles.backBtn} onClick={onExit}>
          戻る
        </button>
      </div>
    )
  }

  if (state.phase === 'empty') {
    const emptyText =
      kind === 'review'
        ? '今すぐ復習する項目はありません'
        : kind === 'today'
          ? '今日は学習できる項目がありません'
          : '練習できる学習項目がありません。候補を採用してから学習してください'
    return (
      <div style={styles.errorBox} role="status">
        <p style={styles.errorText}>{emptyText}</p>
        <button type="button" style={styles.backBtn} onClick={onExit}>
          戻る
        </button>
      </div>
    )
  }

  if (state.phase === 'session-result' && state.session) {
    return (
      <PracticeSessionResult
        variant={kind}
        correctCount={state.correctCount}
        wrongAnswers={state.wrongAnswers}
        sessionTotal={state.session.generated_count}
        remainingDue={kind === 'review' || kind === 'today' ? remainingDue : null}
        reviewCount={state.todayMeta?.reviewCount}
        newCount={state.todayMeta?.newCount}
        onRetry={() => {
          void retry()
        }}
        onBack={onExit}
      />
    )
  }

  if (
    (state.phase === 'answering' || state.phase === 'result') &&
    current
  ) {
    return (
      <PracticeExerciseCard
        exercise={current}
        item={currentItem}
        input={state.input}
        reconstruction={state.reconstruction}
        feedback={state.feedback}
        submitting={state.submitting}
        submitError={state.submitError}
        inputRef={inputRef}
        questionNum={state.questionIndex + 1}
        sessionTotal={state.session?.generated_count ?? 0}
        activityLabel={
          currentTodayEntry ? todayActivityLabel(currentTodayEntry.activity_kind) : null
        }
        reasonLabels={visibleEntryReasons(currentTodayEntry)}
        onInputChange={setInput}
        onReconstructionChange={setReconstruction}
        onSubmit={() => {
          void submit()
        }}
        onChoice={option => {
          void submitChoice(option)
        }}
        onNext={nextQuestion}
      />
    )
  }

  return (
    <p style={styles.msg} role="status">
      読み込み中...
    </p>
  )
}

const styles: Record<string, React.CSSProperties> = {
  msg: {
    textAlign: 'center',
    color: '#666',
    fontSize: 16,
    marginTop: 40,
  },
  errorBox: {
    textAlign: 'center',
    padding: 24,
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
  },
  errorText: {
    margin: '0 0 16px',
    color: '#444',
    fontSize: 15,
    lineHeight: 1.5,
  },
  primaryBtn: {
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
  backBtn: {
    marginTop: 12,
    fontSize: 15,
    fontWeight: 500,
    padding: '10px 24px',
    minHeight: 44,
    borderRadius: 12,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#666',
    cursor: 'pointer',
    width: '100%',
  },
}

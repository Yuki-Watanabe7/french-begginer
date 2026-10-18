import { useCallback, useEffect, useRef, useState } from 'react'
import {
  clearItemKnown,
  createPracticeSession,
  createReviewSession,
  createTodaySession,
  fetchTutorItem,
  fetchTutorItems,
  markItemKnown,
  submitExerciseAnswer,
} from '../api/tutor'
import type {
  ExerciseFeedback,
  ExerciseView,
  LearningItem,
  PracticeWrongAnswer,
  TodayLearningSession,
  TodayPlanEntryView,
  TutorSessionKind,
} from '../types'
import {
  formatPracticeGiven,
  tutorExerciseAnswerErrorMessage,
  tutorKnownItemErrorMessage,
  tutorPracticeSessionErrorMessage,
  tutorReviewSessionErrorMessage,
  tutorTodaySessionErrorMessage,
} from '../utils/tutor'

export type PracticePhase =
  | 'loading'
  | 'empty'
  | 'answering'
  | 'result'
  | 'session-result'
  | 'error'

export interface TodaySessionMeta {
  reviewCount: number
  newCount: number
  deferredDueCount: number
  entries: TodayPlanEntryView[]
}

export interface PracticeSessionState {
  phase: PracticePhase
  session: {
    session_id: string
    exercises: ExerciseView[]
    requested_count: number
    generated_count: number
  } | null
  todayMeta: TodaySessionMeta | null
  questionIndex: number
  feedback: ExerciseFeedback | null
  input: string
  reconstruction: number[]
  submitting: boolean
  submitError: string | null
  error: string | null
  correctCount: number
  wrongAnswers: PracticeWrongAnswer[]
  knownByItemId: Record<string, boolean>
  knownBusy: boolean
  knownError: string | null
}

const ITEM_LIST_LIMIT = 100

function newEventId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `evt-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function initialState(): PracticeSessionState {
  return {
    phase: 'loading',
    session: null,
    todayMeta: null,
    questionIndex: 0,
    feedback: null,
    input: '',
    reconstruction: [],
    submitting: false,
    submitError: null,
    error: null,
    correctCount: 0,
    wrongAnswers: [],
    knownByItemId: {},
    knownBusy: false,
    knownError: null,
  }
}

function currentExercise(state: PracticeSessionState): ExerciseView | null {
  return state.session?.exercises[state.questionIndex] ?? null
}

async function loadItemsById(exercises: ExerciseView[]): Promise<Record<string, LearningItem>> {
  const byId: Record<string, LearningItem> = {}
  try {
    const items = await fetchTutorItems({ limit: ITEM_LIST_LIMIT })
    for (const item of items) {
      byId[item.id] = item
    }
  } catch {
    // meaning_ja は補助情報。Item 一覧の失敗で Session 全体を止めない。
  }
  const missing = [...new Set(exercises.map(row => row.learning_item_id))].filter(
    id => byId[id] === undefined,
  )
  await Promise.all(
    missing.map(async id => {
      try {
        byId[id] = await fetchTutorItem(id)
      } catch {
        // 個別取得失敗も Session は継続する。
      }
    }),
  )
  return byId
}

function enrichFeedback(
  feedback: ExerciseFeedback,
  item: LearningItem | undefined,
): ExerciseFeedback {
  return {
    ...feedback,
    meaning_ja: item?.meaning_ja ?? feedback.meaning_ja,
    canonical_form: item?.canonical_form ?? feedback.canonical_form,
  }
}

function sessionStartErrorMessage(kind: TutorSessionKind, error: unknown): string {
  if (kind === 'today') return tutorTodaySessionErrorMessage(error)
  if (kind === 'review') return tutorReviewSessionErrorMessage(error)
  return tutorPracticeSessionErrorMessage(error)
}

async function startSession(kind: TutorSessionKind, sourceId: string | undefined, questionCount: number) {
  if (kind === 'today') {
    // 出題数の選択画面は挟まない。件数は学習状態の自動調整に任せる。
    return createTodaySession({})
  }
  if (kind === 'review') {
    return createReviewSession({ question_count: questionCount })
  }
  return createPracticeSession({
    source_id: sourceId,
    question_count: questionCount,
  })
}

function isTodaySession(
  session: Awaited<ReturnType<typeof startSession>>,
): session is TodayLearningSession {
  return (
    'entries' in session &&
    'review_count' in session &&
    'new_count' in session &&
    'deferred_due_count' in session
  )
}

function todayMetaFromSession(
  kind: TutorSessionKind,
  session: Awaited<ReturnType<typeof startSession>>,
): TodaySessionMeta | null {
  if (kind !== 'today' || !isTodaySession(session)) return null
  return {
    reviewCount: session.review_count,
    newCount: session.new_count,
    deferredDueCount: session.deferred_due_count,
    entries: session.entries,
  }
}

export function usePracticeSession(
  sourceId: string | undefined,
  questionCount: number,
  kind: TutorSessionKind = 'practice',
) {
  const [state, setState] = useState<PracticeSessionState>(initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const itemsRef = useRef<Record<string, LearningItem>>({})
  const submittingRef = useRef(false)
  const knownBusyRef = useRef(false)
  const startGenerationRef = useRef<object | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const sourceIdRef = useRef(sourceId)
  const questionCountRef = useRef(questionCount)
  const kindRef = useRef(kind)
  sourceIdRef.current = sourceId
  questionCountRef.current = questionCount
  kindRef.current = kind

  const start = useCallback(async () => {
    submittingRef.current = false
    knownBusyRef.current = false
    itemsRef.current = {}
    setState({
      ...initialState(),
      phase: 'loading',
    })
    const generation = {}
    startGenerationRef.current = generation
    try {
      const session = await startSession(
        kindRef.current,
        sourceIdRef.current,
        questionCountRef.current,
      )
      if (startGenerationRef.current !== generation) return
      const todayMeta = todayMetaFromSession(kindRef.current, session)
      if (session.exercises.length === 0) {
        setState(s => ({ ...s, phase: 'empty', session, todayMeta }))
        return
      }
      const items = await loadItemsById(session.exercises)
      if (startGenerationRef.current !== generation) return
      itemsRef.current = items
      setState(s => ({
        ...s,
        phase: 'answering',
        session,
        todayMeta,
        questionIndex: 0,
        feedback: null,
        input: '',
        reconstruction: [],
        submitError: null,
        error: null,
        correctCount: 0,
        wrongAnswers: [],
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch (error) {
      if (startGenerationRef.current !== generation) return
      const message = sessionStartErrorMessage(kindRef.current, error)
      setState(s => ({
        ...s,
        phase: 'error',
        error: message,
      }))
    }
  }, [])

  useEffect(() => {
    void start()
  }, [start])

  const current = currentExercise(state)

  const submitAnswer = useCallback(async (answer: string | string[]) => {
    const snapshot = stateRef.current
    const exercise = currentExercise(snapshot)
    if (!exercise || snapshot.phase !== 'answering' || submittingRef.current) return
    submittingRef.current = true
    setState(s => ({ ...s, submitting: true, submitError: null }))
    try {
      const raw = await submitExerciseAnswer(
        exercise.learning_item_id,
        exercise.exercise_type,
        answer,
        { id: newEventId() },
      )
      const item = itemsRef.current[exercise.learning_item_id]
      const feedback = enrichFeedback(raw, item)
      setState(s => {
        const next: PracticeSessionState = {
          ...s,
          phase: 'result',
          feedback,
          submitting: false,
          submitError: null,
        }
        if (feedback.correct) {
          next.correctCount = s.correctCount + 1
        } else {
          next.wrongAnswers = [
            ...s.wrongAnswers,
            {
              prompt: exercise.prompt,
              exerciseType: exercise.exercise_type,
              correctAnswer: feedback.correct_answer,
              userAnswer: formatPracticeGiven(feedback.given),
            },
          ]
        }
        return next
      })
    } catch (error) {
      setState(s => ({
        ...s,
        phase: 'answering',
        submitting: false,
        submitError: tutorExerciseAnswerErrorMessage(error),
      }))
    } finally {
      submittingRef.current = false
    }
  }, [])

  const submit = useCallback(async () => {
    const snapshot = stateRef.current
    const exercise = currentExercise(snapshot)
    if (!exercise || snapshot.phase !== 'answering') return
    if (exercise.response_kind === 'reconstruction') {
      const options = exercise.options ?? []
      const tokens = snapshot.reconstruction.map(index => options[index]).filter(Boolean)
      if (tokens.length === 0) return
      await submitAnswer(tokens)
      return
    }
    if (snapshot.input.trim() === '') return
    await submitAnswer(snapshot.input)
  }, [submitAnswer])

  const submitChoice = useCallback(
    async (option: string) => {
      const snapshot = stateRef.current
      if (snapshot.phase !== 'answering') return
      await submitAnswer(option)
    },
    [submitAnswer],
  )

  const nextQuestion = useCallback(() => {
    const snapshot = stateRef.current
    if (snapshot.phase !== 'result' || !snapshot.session) return
    const nextIndex = snapshot.questionIndex + 1
    if (nextIndex >= snapshot.session.exercises.length) {
      setState(s => ({ ...s, phase: 'session-result', knownError: null }))
      return
    }
    setState(s => ({
      ...s,
      phase: 'answering',
      questionIndex: nextIndex,
      feedback: null,
      input: '',
      reconstruction: [],
      submitting: false,
      submitError: null,
      knownError: null,
    }))
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const setInput = useCallback((value: string) => {
    setState(s => ({ ...s, input: value }))
  }, [])

  const setReconstruction = useCallback((indices: number[]) => {
    setState(s => ({ ...s, reconstruction: indices }))
  }, [])

  const changeKnown = useCallback(async (mark: boolean) => {
    const snapshot = stateRef.current
    const exercise = currentExercise(snapshot)
    if (!exercise || knownBusyRef.current || submittingRef.current) return
    if ((snapshot.knownByItemId[exercise.learning_item_id] === true) === mark) return
    knownBusyRef.current = true
    setState(s => ({ ...s, knownBusy: true, knownError: null }))
    try {
      const result = mark
        ? await markItemKnown(exercise.learning_item_id)
        : await clearItemKnown(exercise.learning_item_id)
      setState(s => ({
        ...s,
        knownBusy: false,
        knownError: null,
        knownByItemId: {
          ...s.knownByItemId,
          [exercise.learning_item_id]: result.explicit_known,
        },
      }))
    } catch (error) {
      setState(s => ({
        ...s,
        knownBusy: false,
        knownError: tutorKnownItemErrorMessage(error),
      }))
    } finally {
      knownBusyRef.current = false
    }
  }, [])

  const skipUnanswered = useCallback(() => {
    const snapshot = stateRef.current
    if (snapshot.phase !== 'answering' || !snapshot.session || submittingRef.current) return
    const nextIndex = snapshot.questionIndex + 1
    if (nextIndex >= snapshot.session.exercises.length) {
      setState(s => ({ ...s, phase: 'session-result', knownError: null }))
      return
    }
    setState(s => ({
      ...s,
      phase: 'answering',
      questionIndex: nextIndex,
      feedback: null,
      input: '',
      reconstruction: [],
      submitting: false,
      submitError: null,
      knownError: null,
    }))
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const currentItem = current
    ? itemsRef.current[current.learning_item_id]
    : undefined
  const currentTodayEntry = state.todayMeta?.entries[state.questionIndex] ?? null

  return {
    state,
    current,
    currentItem,
    currentTodayEntry,
    inputRef,
    submit,
    submitChoice,
    nextQuestion,
    skipUnanswered,
    markKnown: () => {
      void changeKnown(true)
    },
    undoKnown: () => {
      void changeKnown(false)
    },
    setInput,
    setReconstruction,
    retry: start,
  }
}

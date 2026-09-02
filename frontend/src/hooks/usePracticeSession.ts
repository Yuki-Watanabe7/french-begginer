import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createPracticeSession,
  createReviewSession,
  fetchTutorItem,
  fetchTutorItems,
  submitExerciseAnswer,
} from '../api/tutor'
import type {
  ExerciseFeedback,
  ExerciseView,
  LearningItem,
  PracticeWrongAnswer,
  TutorSessionKind,
} from '../types'
import {
  formatPracticeGiven,
  tutorExerciseAnswerErrorMessage,
  tutorPracticeSessionErrorMessage,
  tutorReviewSessionErrorMessage,
} from '../utils/tutor'

export type PracticePhase =
  | 'loading'
  | 'empty'
  | 'answering'
  | 'result'
  | 'session-result'
  | 'error'

export interface PracticeSessionState {
  phase: PracticePhase
  session: {
    session_id: string
    exercises: ExerciseView[]
    requested_count: number
    generated_count: number
  } | null
  questionIndex: number
  feedback: ExerciseFeedback | null
  input: string
  reconstruction: number[]
  submitting: boolean
  submitError: string | null
  error: string | null
  correctCount: number
  wrongAnswers: PracticeWrongAnswer[]
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
    questionIndex: 0,
    feedback: null,
    input: '',
    reconstruction: [],
    submitting: false,
    submitError: null,
    error: null,
    correctCount: 0,
    wrongAnswers: [],
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
    itemsRef.current = {}
    setState({
      ...initialState(),
      phase: 'loading',
    })
    const generation = {}
    startGenerationRef.current = generation
    try {
      const session =
        kindRef.current === 'review'
          ? await createReviewSession({
              question_count: questionCountRef.current,
            })
          : await createPracticeSession({
              source_id: sourceIdRef.current,
              question_count: questionCountRef.current,
            })
      if (startGenerationRef.current !== generation) return
      if (session.exercises.length === 0) {
        setState(s => ({ ...s, phase: 'empty', session }))
        return
      }
      const items = await loadItemsById(session.exercises)
      if (startGenerationRef.current !== generation) return
      itemsRef.current = items
      setState(s => ({
        ...s,
        phase: 'answering',
        session,
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
      const message =
        kindRef.current === 'review'
          ? tutorReviewSessionErrorMessage(error)
          : tutorPracticeSessionErrorMessage(error)
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
      setState(s => ({ ...s, phase: 'session-result' }))
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
    }))
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const setInput = useCallback((value: string) => {
    setState(s => ({ ...s, input: value }))
  }, [])

  const setReconstruction = useCallback((indices: number[]) => {
    setState(s => ({ ...s, reconstruction: indices }))
  }, [])

  const currentItem = current
    ? itemsRef.current[current.learning_item_id]
    : undefined

  return {
    state,
    current,
    currentItem,
    inputRef,
    submit,
    submitChoice,
    nextQuestion,
    setInput,
    setReconstruction,
    retry: start,
  }
}

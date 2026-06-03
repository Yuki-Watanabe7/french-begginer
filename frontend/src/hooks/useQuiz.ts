import { useCallback, useRef, useState } from 'react'
import { checkAnswer, fetchSessionQuestions } from '../api/client'
import type { AnswerResult, Question, VerbFilter, VerbGroup, VerbLevel, VerbPattern, WrongAnswer } from '../types'

type Phase = 'setup' | 'quiz-settings' | 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface State {
  phase: Phase
  group: VerbGroup
  level: VerbLevel | undefined
  pattern: VerbPattern | undefined
  question: Question | null
  result: AnswerResult | null
  input: string
  error: string | null
  questionNum: number
  sessionTotal: number
  normalSessionTotal: number
  correctCount: number
  wrongAnswers: WrongAnswer[]
  reviewQueue: Question[]
  isReviewPhase: boolean
  firstCorrectCount: number
  reviewCorrectCount: number
  sessionQueue: Question[]
}

const DEFAULT_SESSION_SIZE = 10

const initialState = (): State => ({
  phase: 'setup',
  group: 'all',
  level: undefined,
  pattern: undefined,
  question: null,
  result: null,
  input: '',
  error: null,
  questionNum: 1,
  sessionTotal: DEFAULT_SESSION_SIZE,
  normalSessionTotal: DEFAULT_SESSION_SIZE,
  correctCount: 0,
  wrongAnswers: [],
  reviewQueue: [],
  isReviewPhase: false,
  firstCorrectCount: 0,
  reviewCorrectCount: 0,
  sessionQueue: [],
})

export function useQuiz() {
  const [state, setState] = useState<State>(initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const inputRef = useRef<HTMLInputElement>(null)

  const selectGroup = useCallback((filter: VerbFilter) => {
    setState(s => ({ ...s, phase: 'quiz-settings', group: filter.group, level: filter.level, pattern: filter.pattern }))
  }, [])

  const startSession = useCallback(async (sessionSize: number) => {
    const { group, level, pattern } = stateRef.current
    setState(s => ({
      ...s,
      phase: 'loading',
      question: null,
      result: null,
      input: '',
      error: null,
      questionNum: 1,
      sessionTotal: sessionSize,
      normalSessionTotal: sessionSize,
      correctCount: 0,
      wrongAnswers: [],
      reviewQueue: [],
      isReviewPhase: false,
      firstCorrectCount: 0,
      reviewCorrectCount: 0,
      sessionQueue: [],
    }))
    try {
      const questions = await fetchSessionQuestions(sessionSize, group, level, pattern)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
        normalSessionTotal: questions.length,
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const retryLoad = useCallback(async () => {
    const { group, level, pattern, normalSessionTotal } = stateRef.current
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null, questionNum: 1, sessionQueue: [] }))
    try {
      const questions = await fetchSessionQuestions(normalSessionTotal, group, level, pattern)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const submit = useCallback(async () => {
    const { question, input, isReviewPhase } = stateRef.current
    if (!question || input.trim() === '') return
    try {
      const result = await checkAnswer(question.verb, question.tense, question.pronoun, input)
      if (result.correct) {
        if (isReviewPhase) {
          setState(s => ({ ...s, phase: 'result', result, reviewCorrectCount: s.reviewCorrectCount + 1 }))
        } else {
          setState(s => ({ ...s, phase: 'result', result, correctCount: s.correctCount + 1 }))
        }
      } else {
        if (isReviewPhase) {
          setState(s => ({ ...s, phase: 'result', result, reviewQueue: [...s.reviewQueue, question] }))
        } else {
          const wrong: WrongAnswer = {
            verb: question.verb,
            tense: question.tense,
            pronoun: question.pronoun,
            correctAnswer: result.expected,
            userAnswer: input,
          }
          setState(s => {
            const isDuplicate = s.wrongAnswers.some(
              w => w.verb === wrong.verb && w.tense === wrong.tense && w.pronoun === wrong.pronoun,
            )
            if (isDuplicate) return { ...s, phase: 'result', result }
            return { ...s, phase: 'result', result, wrongAnswers: [...s.wrongAnswers, wrong] }
          })
        }
      }
    } catch {
      setState(s => ({ ...s, phase: 'error', error: '判定に失敗しました' }))
    }
  }, [])

  const nextQuestion = useCallback(() => {
    const { questionNum, sessionTotal, reviewQueue, isReviewPhase, correctCount, wrongAnswers } =
      stateRef.current

    if (isReviewPhase) {
      if (reviewQueue.length === 0) {
        setState(s => ({ ...s, phase: 'session-result' }))
        return
      }
      const [next, ...rest] = reviewQueue
      setState(s => ({
        ...s,
        phase: 'answering',
        question: next,
        result: null,
        input: '',
        questionNum: s.questionNum + 1,
        reviewQueue: rest,
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
      return
    }

    // Normal phase
    if (questionNum >= sessionTotal) {
      if (wrongAnswers.length > 0) {
        const queue: Question[] = wrongAnswers.map(w => ({
          verb: w.verb,
          tense: w.tense,
          pronoun: w.pronoun,
        }))
        const [first, ...rest] = queue
        setState(s => ({
          ...s,
          phase: 'answering',
          question: first,
          result: null,
          input: '',
          isReviewPhase: true,
          firstCorrectCount: correctCount,
          reviewCorrectCount: 0,
          questionNum: 1,
          sessionTotal: queue.length,
          reviewQueue: rest,
        }))
        setTimeout(() => inputRef.current?.focus(), 50)
      } else {
        setState(s => ({ ...s, phase: 'session-result', firstCorrectCount: correctCount }))
      }
      return
    }

    const nextNum = questionNum + 1
    const [nextQ, ...remainingQueue] = stateRef.current.sessionQueue
    setState(s => ({
      ...s,
      phase: 'answering',
      question: nextQ,
      result: null,
      input: '',
      error: null,
      questionNum: nextNum,
      sessionQueue: remainingQueue,
    }))
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const startNewSession = useCallback(async () => {
    const { group, level, pattern, normalSessionTotal } = stateRef.current
    setState(s => ({
      ...s,
      phase: 'loading',
      question: null,
      result: null,
      input: '',
      error: null,
      questionNum: 1,
      sessionTotal: normalSessionTotal,
      correctCount: 0,
      wrongAnswers: [],
      reviewQueue: [],
      isReviewPhase: false,
      firstCorrectCount: 0,
      reviewCorrectCount: 0,
      sessionQueue: [],
    }))
    try {
      const questions = await fetchSessionQuestions(normalSessionTotal, group, level, pattern)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
        normalSessionTotal: questions.length,
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const backToSetup = useCallback(() => {
    setState(initialState())
  }, [])

  const setInput = useCallback((v: string) => {
    setState(s => ({ ...s, input: v }))
  }, [])

  return {
    state,
    inputRef,
    submit,
    setInput,
    nextQuestion,
    selectGroup,
    startSession,
    startNewSession,
    backToSetup,
    retryLoad,
  }
}

import { useCallback, useRef, useState } from 'react'
import { checkNounArticleAnswer, fetchNextNounArticleQuestion } from '../api/client'
import type { NounArticleAnswerResult, NounArticleQuestion, NounArticleWrongAnswer, NounFilter } from '../types'

type NounArticlePhase = 'noun-filter' | 'quiz-settings' | 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface NounArticleState {
  phase: NounArticlePhase
  filter: NounFilter
  question: NounArticleQuestion | null
  result: NounArticleAnswerResult | null
  input: string
  error: string | null
  questionNum: number
  sessionTotal: number
  normalSessionTotal: number
  correctCount: number
  wrongAnswers: NounArticleWrongAnswer[]
  reviewQueue: NounArticleQuestion[]
  isReviewPhase: boolean
  firstCorrectCount: number
  reviewCorrectCount: number
}

const DEFAULT_SESSION_SIZE = 10

const initialNounArticleState = (): NounArticleState => ({
  phase: 'noun-filter',
  filter: {},
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
})

export function useNounArticleQuiz() {
  const [state, setState] = useState<NounArticleState>(initialNounArticleState)
  const stateRef = useRef(state)
  stateRef.current = state
  const inputRef = useRef<HTMLInputElement>(null)

  const selectFilter = useCallback((filter: NounFilter) => {
    setState(s => ({ ...s, filter, phase: 'quiz-settings' }))
  }, [])

  const backToFilter = useCallback(() => {
    setState(s => ({ ...s, phase: 'noun-filter' }))
  }, [])

  const startSession = useCallback(async (sessionSize: number) => {
    const { filter } = stateRef.current
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
    }))
    try {
      const q = await fetchNextNounArticleQuestion(filter)
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const retryLoad = useCallback(async () => {
    const { filter } = stateRef.current
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null }))
    try {
      const q = await fetchNextNounArticleQuestion(filter)
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const submit = useCallback(async () => {
    const { question, input, isReviewPhase } = stateRef.current
    if (!question || input.trim() === '') return
    try {
      const result = await checkNounArticleAnswer(question.noun, input)
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
          const wrong: NounArticleWrongAnswer = {
            noun: question.noun,
            meaning_ja: question.meaning_ja,
            correctAnswer: result.expected,
            userAnswer: input,
          }
          setState(s => {
            const isDuplicate = s.wrongAnswers.some(w => w.noun === wrong.noun)
            if (isDuplicate) return { ...s, phase: 'result', result }
            return { ...s, phase: 'result', result, wrongAnswers: [...s.wrongAnswers, wrong] }
          })
        }
      }
    } catch {
      setState(s => ({ ...s, phase: 'error', error: '判定に失敗しました' }))
    }
  }, [])

  const nextQuestion = useCallback(async () => {
    const { questionNum, sessionTotal, reviewQueue, isReviewPhase, correctCount, wrongAnswers, filter } =
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

    if (questionNum >= sessionTotal) {
      if (wrongAnswers.length > 0) {
        const queue: NounArticleQuestion[] = wrongAnswers.map(w => ({
          noun: w.noun,
          meaning_ja: w.meaning_ja,
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
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null, questionNum: nextNum }))
    try {
      const q = await fetchNextNounArticleQuestion(filter)
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const startNewSession = useCallback(async () => {
    const { normalSessionTotal, filter } = stateRef.current
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
    }))
    try {
      const q = await fetchNextNounArticleQuestion(filter)
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const backToSetup = useCallback(() => {
    setState(initialNounArticleState())
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
    startSession,
    startNewSession,
    selectFilter,
    backToFilter,
    backToSetup,
    retryLoad,
  }
}

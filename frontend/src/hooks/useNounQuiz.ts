import { useCallback, useRef, useState } from 'react'
import { checkNounAnswer, fetchNextNounQuestion } from '../api/client'
import type { NounGender, NounGenderAnswerResult, NounGenderQuestion, NounWrongAnswer } from '../types'

type NounPhase = 'quiz-settings' | 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface NounState {
  phase: NounPhase
  question: NounGenderQuestion | null
  result: NounGenderAnswerResult | null
  error: string | null
  questionNum: number
  sessionTotal: number
  normalSessionTotal: number
  correctCount: number
  wrongAnswers: NounWrongAnswer[]
  reviewQueue: NounGenderQuestion[]
  isReviewPhase: boolean
  firstCorrectCount: number
  reviewCorrectCount: number
}

const DEFAULT_SESSION_SIZE = 10

const initialNounState = (): NounState => ({
  phase: 'quiz-settings',
  question: null,
  result: null,
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

export function useNounQuiz() {
  const [state, setState] = useState<NounState>(initialNounState)
  const stateRef = useRef(state)
  stateRef.current = state

  const startSession = useCallback(async (sessionSize: number) => {
    setState(s => ({
      ...s,
      phase: 'loading',
      question: null,
      result: null,
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
      const q = await fetchNextNounQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const retryLoad = useCallback(async () => {
    setState(s => ({ ...s, phase: 'loading', result: null, error: null }))
    try {
      const q = await fetchNextNounQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const submit = useCallback(async (answer: NounGender) => {
    const { question, isReviewPhase } = stateRef.current
    if (!question) return
    try {
      const result = await checkNounAnswer(question.noun, answer)
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
          const wrong: NounWrongAnswer = {
            noun: question.noun,
            meaning_ja: question.meaning_ja,
            correctGender: result.expected,
            userAnswer: answer,
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
        questionNum: s.questionNum + 1,
        reviewQueue: rest,
      }))
      return
    }

    if (questionNum >= sessionTotal) {
      if (wrongAnswers.length > 0) {
        const queue: NounGenderQuestion[] = wrongAnswers.map(w => ({
          noun: w.noun,
          meaning_ja: w.meaning_ja,
        }))
        const [first, ...rest] = queue
        setState(s => ({
          ...s,
          phase: 'answering',
          question: first,
          result: null,
          isReviewPhase: true,
          firstCorrectCount: correctCount,
          reviewCorrectCount: 0,
          questionNum: 1,
          sessionTotal: queue.length,
          reviewQueue: rest,
        }))
      } else {
        setState(s => ({ ...s, phase: 'session-result', firstCorrectCount: correctCount }))
      }
      return
    }

    const nextNum = questionNum + 1
    setState(s => ({ ...s, phase: 'loading', result: null, error: null, questionNum: nextNum }))
    try {
      const q = await fetchNextNounQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const startNewSession = useCallback(async () => {
    const { normalSessionTotal } = stateRef.current
    setState(s => ({
      ...s,
      phase: 'loading',
      question: null,
      result: null,
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
      const q = await fetchNextNounQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const backToSetup = useCallback(() => {
    setState(initialNounState())
  }, [])

  return {
    state,
    submit,
    nextQuestion,
    startSession,
    startNewSession,
    backToSetup,
    retryLoad,
  }
}

import { useCallback, useRef, useState } from 'react'
import { checkNounAnswer, fetchNounSessionQuestions } from '../api/client'
import type { NounFilter, NounGender, NounGenderAnswerResult, NounGenderQuestion, NounWrongAnswer } from '../types'

type NounPhase = 'noun-filter' | 'quiz-settings' | 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface NounState {
  phase: NounPhase
  filter: NounFilter
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
  sessionQueue: NounGenderQuestion[]
}

const DEFAULT_SESSION_SIZE = 10

const initialNounState = (): NounState => ({
  phase: 'noun-filter',
  filter: {},
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
  sessionQueue: [],
})

export function useNounQuiz() {
  const [state, setState] = useState<NounState>(initialNounState)
  const stateRef = useRef(state)
  stateRef.current = state

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
      const questions = await fetchNounSessionQuestions(sessionSize, filter)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
        normalSessionTotal: questions.length,
      }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const retryLoad = useCallback(async () => {
    const { filter, normalSessionTotal } = stateRef.current
    setState(s => ({ ...s, phase: 'loading', result: null, error: null, questionNum: 1, sessionQueue: [] }))
    try {
      const questions = await fetchNounSessionQuestions(normalSessionTotal, filter)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
      }))
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
            article_indefinite: question.article_indefinite,
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
          article_indefinite: w.article_indefinite,
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
    const [nextQ, ...remainingQueue] = stateRef.current.sessionQueue
    setState(s => ({
      ...s,
      phase: 'answering',
      question: nextQ,
      result: null,
      error: null,
      questionNum: nextNum,
      sessionQueue: remainingQueue,
    }))
  }, [])

  const startNewSession = useCallback(async () => {
    const { normalSessionTotal, filter } = stateRef.current
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
      sessionQueue: [],
    }))
    try {
      const questions = await fetchNounSessionQuestions(normalSessionTotal, filter)
      const [first, ...rest] = questions
      setState(s => ({
        ...s,
        phase: 'answering',
        question: first,
        sessionQueue: rest,
        sessionTotal: questions.length,
        normalSessionTotal: questions.length,
      }))
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
    selectFilter,
    backToFilter,
    backToSetup,
    retryLoad,
  }
}

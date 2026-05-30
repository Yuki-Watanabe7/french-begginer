import { useCallback, useEffect, useRef, useState } from 'react'
import { checkAnswer, fetchNextQuestion } from '../api/client'
import type { AnswerResult, Question, WrongAnswer } from '../types'

type Phase = 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface State {
  phase: Phase
  question: Question | null
  result: AnswerResult | null
  input: string
  error: string | null
  questionNum: number
  sessionTotal: number
  correctCount: number
  wrongAnswers: WrongAnswer[]
  reviewQueue: Question[]
}

const SESSION_SIZE = 10

const newSessionState = (): State => ({
  phase: 'loading',
  question: null,
  result: null,
  input: '',
  error: null,
  questionNum: 1,
  sessionTotal: SESSION_SIZE,
  correctCount: 0,
  wrongAnswers: [],
  reviewQueue: [],
})

export function useQuiz() {
  const [state, setState] = useState<State>(newSessionState)
  const stateRef = useRef(state)
  stateRef.current = state
  const inputRef = useRef<HTMLInputElement>(null)

  const retryLoad = useCallback(async () => {
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null }))
    try {
      const q = await fetchNextQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  useEffect(() => {
    void retryLoad()
  }, [retryLoad])

  const submit = useCallback(async () => {
    const { question, input } = stateRef.current
    if (!question || input.trim() === '') return
    try {
      const result = await checkAnswer(question.verb, question.tense, question.pronoun, input)
      if (result.correct) {
        setState(s => ({ ...s, phase: 'result', result, correctCount: s.correctCount + 1 }))
      } else {
        const wrong: WrongAnswer = {
          verb: question.verb,
          tense: question.tense,
          pronoun: question.pronoun,
          correctAnswer: result.expected,
          userAnswer: input,
        }
        setState(s => ({ ...s, phase: 'result', result, wrongAnswers: [...s.wrongAnswers, wrong] }))
      }
    } catch {
      setState(s => ({ ...s, phase: 'error', error: '判定に失敗しました' }))
    }
  }, [])

  const nextQuestion = useCallback(async () => {
    const { questionNum, sessionTotal, reviewQueue } = stateRef.current
    if (questionNum >= sessionTotal) {
      setState(s => ({ ...s, phase: 'session-result' }))
      return
    }
    const nextNum = questionNum + 1
    if (reviewQueue.length > 0) {
      const [next, ...rest] = reviewQueue
      setState(s => ({
        ...s,
        phase: 'answering',
        question: next,
        result: null,
        input: '',
        questionNum: nextNum,
        reviewQueue: rest,
      }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } else {
      setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null, questionNum: nextNum }))
      try {
        const q = await fetchNextQuestion()
        setState(s => ({ ...s, phase: 'answering', question: q }))
        setTimeout(() => inputRef.current?.focus(), 50)
      } catch {
        setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
      }
    }
  }, [])

  const startNewSession = useCallback(async () => {
    setState(newSessionState())
    try {
      const q = await fetchNextQuestion()
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const startReview = useCallback(() => {
    const { wrongAnswers } = stateRef.current
    if (wrongAnswers.length === 0) return
    const queue: Question[] = wrongAnswers.map(w => ({
      verb: w.verb,
      tense: w.tense,
      pronoun: w.pronoun,
    }))
    const [first, ...rest] = queue
    setState({
      phase: 'answering',
      question: first,
      result: null,
      input: '',
      error: null,
      questionNum: 1,
      sessionTotal: wrongAnswers.length,
      correctCount: 0,
      wrongAnswers: [],
      reviewQueue: rest,
    })
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const setInput = useCallback((v: string) => {
    setState(s => ({ ...s, input: v }))
  }, [])

  return { state, inputRef, submit, setInput, nextQuestion, startNewSession, startReview, retryLoad }
}

import { useCallback, useRef, useState } from 'react'
import { checkAnswer, fetchNextQuestion } from '../api/client'
import type { AnswerResult, Question, VerbGroup, WrongAnswer } from '../types'

type Phase = 'setup' | 'loading' | 'answering' | 'result' | 'session-result' | 'error'

interface State {
  phase: Phase
  verbGroup: VerbGroup
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

const setupState = (): State => ({
  phase: 'setup',
  verbGroup: 'all',
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

const groupParam = (g: VerbGroup) => (g === 'all' ? undefined : g)

export function useQuiz() {
  const [state, setState] = useState<State>(setupState)
  const stateRef = useRef(state)
  stateRef.current = state
  const inputRef = useRef<HTMLInputElement>(null)

  const startSession = useCallback(async (group: VerbGroup) => {
    setState({
      phase: 'loading',
      verbGroup: group,
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
    try {
      const q = await fetchNextQuestion(groupParam(group))
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  const retryLoad = useCallback(async () => {
    const { verbGroup } = stateRef.current
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null }))
    try {
      const q = await fetchNextQuestion(groupParam(verbGroup))
      setState(s => ({ ...s, phase: 'answering', question: q }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

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
    const { questionNum, sessionTotal, reviewQueue, verbGroup } = stateRef.current
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
        const q = await fetchNextQuestion(groupParam(verbGroup))
        setState(s => ({ ...s, phase: 'answering', question: q }))
        setTimeout(() => inputRef.current?.focus(), 50)
      } catch {
        setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
      }
    }
  }, [])

  const startNewSession = useCallback(() => {
    setState(setupState())
  }, [])

  const startReview = useCallback(() => {
    const { wrongAnswers, verbGroup } = stateRef.current
    if (wrongAnswers.length === 0) return
    const queue: Question[] = wrongAnswers.map(w => ({
      verb: w.verb,
      tense: w.tense,
      pronoun: w.pronoun,
    }))
    const [first, ...rest] = queue
    setState({
      phase: 'answering',
      verbGroup,
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

  return { state, inputRef, submit, setInput, nextQuestion, startNewSession, startReview, retryLoad, startSession }
}

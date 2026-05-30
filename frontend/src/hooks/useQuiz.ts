import { useCallback, useEffect, useRef, useState } from 'react'
import { checkAnswer, fetchNextQuestion } from '../api/client'
import type { AnswerResult, Question, WrongAnswer } from '../types'

export type Phase = 'loading' | 'answering' | 'result' | 'error' | 'session-result'

const SESSION_SIZE = 10

export interface QuizState {
  phase: Phase
  question: Question | null
  result: AnswerResult | null
  input: string
  error: string | null
  questionNum: number
  sessionTotal: number
  correctCount: number
  wrongAnswers: WrongAnswer[]
  reviewQueue: Question[] | null
}

export function useQuiz() {
  const [state, setState] = useState<QuizState>({
    phase: 'loading',
    question: null,
    result: null,
    input: '',
    error: null,
    questionNum: 1,
    sessionTotal: SESSION_SIZE,
    correctCount: 0,
    wrongAnswers: [],
    reviewQueue: null,
  })
  const inputRef = useRef<HTMLInputElement>(null)

  const loadFromAPI = useCallback(async () => {
    setState(s => ({ ...s, phase: 'loading', result: null, input: '', error: null }))
    try {
      const question = await fetchNextQuestion()
      setState(s => ({ ...s, phase: 'answering', question }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } catch {
      setState(s => ({ ...s, phase: 'error', error: 'サーバーに接続できませんでした' }))
    }
  }, [])

  useEffect(() => {
    void loadFromAPI()
  }, [loadFromAPI])

  const submit = useCallback(async () => {
    if (!state.question || state.input.trim() === '') return
    const question = state.question
    const input = state.input
    try {
      const result = await checkAnswer(question.verb, question.tense, question.pronoun, input)
      setState(s => ({
        ...s,
        phase: 'result',
        result,
        correctCount: s.correctCount + (result.correct ? 1 : 0),
        wrongAnswers: result.correct
          ? s.wrongAnswers
          : [...s.wrongAnswers, {
              verb: question.verb,
              tense: question.tense,
              pronoun: question.pronoun,
              correctAnswer: result.expected,
              userAnswer: input,
            }],
      }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: '判定に失敗しました' }))
    }
  }, [state.question, state.input])

  const nextQuestion = useCallback(() => {
    const { questionNum, sessionTotal, reviewQueue } = state
    if (questionNum >= sessionTotal) {
      setState(s => ({ ...s, phase: 'session-result' }))
      return
    }
    const nextNum = questionNum + 1
    if (reviewQueue !== null) {
      const question = reviewQueue[questionNum]
      setState(s => ({ ...s, phase: 'answering', question, result: null, input: '', questionNum: nextNum }))
      setTimeout(() => inputRef.current?.focus(), 50)
    } else {
      setState(s => ({ ...s, questionNum: nextNum }))
      void loadFromAPI()
    }
  }, [state.questionNum, state.sessionTotal, state.reviewQueue, loadFromAPI])

  const startNewSession = useCallback(() => {
    setState({
      phase: 'loading',
      question: null,
      result: null,
      input: '',
      error: null,
      questionNum: 1,
      sessionTotal: SESSION_SIZE,
      correctCount: 0,
      wrongAnswers: [],
      reviewQueue: null,
    })
    void loadFromAPI()
  }, [loadFromAPI])

  const startReview = useCallback(() => {
    const reviewQueue: Question[] = state.wrongAnswers.map(w => ({
      verb: w.verb,
      tense: w.tense,
      pronoun: w.pronoun,
    }))
    if (reviewQueue.length === 0) return
    setState({
      phase: 'answering',
      question: reviewQueue[0],
      result: null,
      input: '',
      error: null,
      questionNum: 1,
      sessionTotal: reviewQueue.length,
      correctCount: 0,
      wrongAnswers: [],
      reviewQueue,
    })
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [state.wrongAnswers])

  const setInput = useCallback((v: string) => {
    setState(s => ({ ...s, input: v }))
  }, [])

  return { state, inputRef, submit, setInput, nextQuestion, startNewSession, startReview }
}

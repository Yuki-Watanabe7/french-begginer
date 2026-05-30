import { useCallback, useEffect, useRef, useState } from 'react'
import { checkAnswer, fetchNextQuestion } from '../api/client'
import type { AnswerResult, Question } from '../types'

type Phase = 'loading' | 'answering' | 'result' | 'error'

interface State {
  phase: Phase
  question: Question | null
  result: AnswerResult | null
  input: string
  error: string | null
}

export function useQuiz() {
  const [state, setState] = useState<State>({
    phase: 'loading',
    question: null,
    result: null,
    input: '',
    error: null,
  })
  const inputRef = useRef<HTMLInputElement>(null)

  const loadQuestion = useCallback(async () => {
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
    void loadQuestion()
  }, [loadQuestion])

  const submit = useCallback(async () => {
    if (!state.question || state.input.trim() === '') return
    try {
      const result = await checkAnswer(
        state.question.verb,
        state.question.tense,
        state.question.pronoun,
        state.input,
      )
      setState(s => ({ ...s, phase: 'result', result }))
    } catch {
      setState(s => ({ ...s, phase: 'error', error: '判定に失敗しました' }))
    }
  }, [state.question, state.input])

  const setInput = useCallback((v: string) => {
    setState(s => ({ ...s, input: v }))
  }, [])

  return { state, inputRef, submit, setInput, loadQuestion }
}

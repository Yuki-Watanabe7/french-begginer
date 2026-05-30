import type { AnswerResult, Question } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchNextQuestion(): Promise<Question> {
  return json(await fetch(`${BASE}/api/questions/next`))
}

export async function checkAnswer(
  verb: string,
  tense: string,
  pronoun: string,
  answer: string,
): Promise<AnswerResult> {
  return json(
    await fetch(`${BASE}/api/answers/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verb, tense, pronoun, answer }),
    }),
  )
}

import type { AnswerResult, Question, VerbGroup } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchNextQuestion(group?: Exclude<VerbGroup, 'all'>): Promise<Question> {
  const url = group ? `${BASE}/api/questions/next?group=${group}` : `${BASE}/api/questions/next`
  return json(await fetch(url))
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

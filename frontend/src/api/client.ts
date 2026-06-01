import type { AnswerResult, NounGender, NounGenderAnswerResult, NounGenderQuestion, Question, VerbGroup } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchNextQuestion(group: VerbGroup = 'all'): Promise<Question> {
  const params = group !== 'all' ? `?group=${group}` : ''
  return json(await fetch(`${BASE}/api/questions/next${params}`))
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

export async function fetchNextNounQuestion(): Promise<NounGenderQuestion> {
  return json(await fetch(`${BASE}/api/nouns/next`))
}

export async function checkNounAnswer(noun: string, answer: NounGender): Promise<NounGenderAnswerResult> {
  return json(
    await fetch(`${BASE}/api/nouns/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ noun, answer }),
    }),
  )
}

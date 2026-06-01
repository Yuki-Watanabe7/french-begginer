import type { AnswerResult, NounArticleAnswerResult, NounArticleQuestion, NounFilter, NounGender, NounGenderAnswerResult, NounGenderQuestion, Question, VerbGroup } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchNextQuestion(group: VerbGroup = 'all'): Promise<Question> {
  const params = group !== 'all' ? `?group=${group}` : ''
  return json(await fetch(`${BASE}/api/questions/next${params}`))
}

export async function fetchSessionQuestions(count: number, group: VerbGroup = 'all'): Promise<Question[]> {
  const params = new URLSearchParams({ count: String(count) })
  if (group !== 'all') params.set('group', group)
  return json(await fetch(`${BASE}/api/questions/session?${params.toString()}`))
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

export async function fetchNextNounQuestion(filter?: NounFilter): Promise<NounGenderQuestion> {
  const params = new URLSearchParams()
  if (filter?.level) params.set('level', filter.level)
  if (filter?.category) params.set('category', filter.category)
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return json(await fetch(`${BASE}/api/nouns/next${query}`))
}

export async function fetchNounSessionQuestions(count: number, filter?: NounFilter): Promise<NounGenderQuestion[]> {
  const params = new URLSearchParams({ count: String(count) })
  if (filter?.level) params.set('level', filter.level)
  if (filter?.category) params.set('category', filter.category)
  return json(await fetch(`${BASE}/api/nouns/session?${params.toString()}`))
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

export async function fetchNextNounArticleQuestion(filter?: NounFilter): Promise<NounArticleQuestion> {
  const params = new URLSearchParams()
  if (filter?.level) params.set('level', filter.level)
  if (filter?.category) params.set('category', filter.category)
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return json(await fetch(`${BASE}/api/nouns/article/next${query}`))
}

export async function fetchNounArticleSessionQuestions(count: number, filter?: NounFilter): Promise<NounArticleQuestion[]> {
  const params = new URLSearchParams({ count: String(count) })
  if (filter?.level) params.set('level', filter.level)
  if (filter?.category) params.set('category', filter.category)
  return json(await fetch(`${BASE}/api/nouns/article/session?${params.toString()}`))
}

export async function checkNounArticleAnswer(noun: string, answer: string): Promise<NounArticleAnswerResult> {
  return json(
    await fetch(`${BASE}/api/nouns/article/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ noun, answer }),
    }),
  )
}

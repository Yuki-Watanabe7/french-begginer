export type VerbGroup = 'all' | 'er' | 'ir' | 'irregular'

export interface Question {
  verb: string
  tense: string
  pronoun: string
}

export interface AnswerResult {
  correct: boolean
  expected: string
  given: string
}

export interface WrongAnswer {
  verb: string
  tense: string
  pronoun: string
  correctAnswer: string
  userAnswer: string
}

export type NounGender = 'masculine' | 'feminine'

export interface NounGenderQuestion {
  noun: string
  meaning_ja: string | null
}

export interface NounGenderAnswerResult {
  correct: boolean
  expected: NounGender
  given: NounGender
}

export interface NounWrongAnswer {
  noun: string
  meaning_ja: string | null
  correctGender: NounGender
  userAnswer: NounGender
}

export type QuizMode = 'verb_conjugation' | 'noun_gender'

export type NounLevel = 'basic' | 'standard' | 'challenge'
export type NounCategory = 'person' | 'home' | 'food' | 'place' | 'time' | 'school' | 'nature' | 'abstract'

export interface NounFilter {
  level?: NounLevel
  category?: NounCategory
}

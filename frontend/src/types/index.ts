export type VerbGroup = 'all' | 'er' | 'ir' | 'irregular'
export type VerbLevel = 'basic' | 'standard' | 'challenge'
export type VerbPattern = 'regular' | 'stem_change' | 'spelling_change' | 'irregular'

export interface VerbFilter {
  group: VerbGroup
  level?: VerbLevel
  pattern?: VerbPattern
}

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
export type ArticleIndefinite = 'un' | 'une'
export type ArticleDefinite = 'le' | 'la' | "l'"

export interface NounGenderQuestion {
  noun: string
  meaning_ja: string | null
  article_indefinite: ArticleIndefinite
}

export interface NounGenderAnswerResult {
  correct: boolean
  expected: NounGender
  given: NounGender
}

export interface NounWrongAnswer {
  noun: string
  meaning_ja: string | null
  article_indefinite: ArticleIndefinite
  correctGender: NounGender
  userAnswer: NounGender
}

export interface NounArticleQuestion {
  noun: string
  meaning_ja: string | null
}

export interface NounArticleAnswerResult {
  correct: boolean
  expected: string
  given: string
}

export interface NounArticleWrongAnswer {
  noun: string
  meaning_ja: string | null
  correctAnswer: string
  userAnswer: string
}

export type QuizMode = 'verb_conjugation' | 'noun_gender' | 'noun_article'

export type NounLevel = 'basic' | 'standard' | 'challenge'
export type NounCategory = 'person' | 'home' | 'food' | 'place' | 'time' | 'school' | 'nature' | 'abstract'

export interface NounFilter {
  level?: NounLevel
  category?: NounCategory
}

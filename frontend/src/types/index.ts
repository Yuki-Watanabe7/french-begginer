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

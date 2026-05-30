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

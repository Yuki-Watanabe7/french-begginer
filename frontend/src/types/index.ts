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

/** Phase 1 は手入力テキストのみ。将来 URL/PDF 等が追加される。 */
export type SourceType = 'manual_text'

export interface SourceDocument {
  id: string
  source_type: SourceType | string
  title: string
  content: string
  language: string
  created_at: string
  metadata: Record<string, unknown>
}

export interface SourceSummary {
  id: string
  source_type: SourceType | string
  title: string
  language: string
  created_at: string
  content_preview: string
}

export interface CreateTutorSourceInput {
  title: string
  content: string
  language?: string
  metadata?: Record<string, unknown>
}

export interface FetchTutorSourcesOptions {
  limit?: number
}

export type LearningItemType = 'vocabulary' | 'expression' | 'grammar' | 'conjugation'
export type CandidateStatus = 'candidate' | 'accepted' | 'rejected'
export type CefrLevel = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2'
export type CandidateFilter = 'all' | 'candidate' | 'accepted' | 'rejected'

export interface EvidenceSpan {
  start: number
  end: number
  text?: string | null
}

export interface LearningItemCandidate {
  id: string
  source_document_id: string
  item_type: LearningItemType
  canonical_form: string
  meaning_ja: string
  explanation_ja: string | null
  level: CefrLevel | null
  evidence_span: EvidenceSpan
  evidence_text: string
  confidence: number | null
  status: CandidateStatus
  extraction_version: string
  created_at: string
}

export interface ExtractCandidatesResponse {
  source_document_id: string
  extraction_version: string
  created: LearningItemCandidate[]
  skipped: LearningItemCandidate[]
}

export interface SourceRef {
  source_document_id: string
  evidence_span?: EvidenceSpan | null
  confidence?: number | null
}

export interface LearningItem {
  id: string
  item_type: LearningItemType
  canonical_form: string
  meaning_ja: string
  explanation_ja: string | null
  level: CefrLevel | null
  source_refs: SourceRef[]
  created_at: string
  status: string
  metadata?: Record<string, unknown>
}

export interface AcceptCandidateResponse {
  candidate: LearningItemCandidate
  item: LearningItem
  merged: boolean
}

export type ExerciseType =
  | 'meaning_recognition'
  | 'fr_to_ja'
  | 'ja_to_fr'
  | 'cloze'
  | 'expression_reconstruction'
  | 'verb_conjugation'
  | 'noun_gender'
  | 'noun_article'

export type SkillDirection = 'recognition' | 'production'
export type ResponseKind = 'choice' | 'text' | 'reconstruction'

/** 出題 DTO。正解は含めない。 */
export interface ExerciseView {
  learning_item_id: string
  exercise_type: ExerciseType
  skill_direction: SkillDirection
  prompt: string
  response_kind: ResponseKind
  options: string[] | null
  source_context: string | null
  exercise_version: string
}

export interface SkippedPracticeItem {
  learning_item_id: string
  skip_reason: string
  detail?: string | null
}

export interface PracticeSession {
  session_id: string
  exercises: ExerciseView[]
  skipped_items: SkippedPracticeItem[]
  requested_count: number
  generated_count: number
}

export interface CreatePracticeSessionInput {
  source_id?: string
  item_ids?: string[]
  question_count?: number
  seed?: string
}

export interface FetchTutorItemsOptions {
  limit?: number
}

/** 回答後 feedback。correct_answer は回答後のみ存在する。 */
export interface ExerciseFeedback {
  correct: boolean
  correct_answer: string
  given: string | string[]
  explanation_ja: string | null
  source_context: string | null
  meaning_ja: string | null
  canonical_form: string | null
}

export interface PracticeWrongAnswer {
  prompt: string
  exerciseType: ExerciseType
  correctAnswer: string
  userAnswer: string
}

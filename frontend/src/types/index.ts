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

/** 作成 API は手入力のまま。種別は Phase 6 の ingestion 契約に合わせる。 */
export type SourceType =
  | 'manual_text'
  | 'web_url'
  | 'pdf'
  | 'youtube_transcript'
  | 'subtitle'
  | 'audio_transcript'
  | 'conversation_log'

/** 正規化後本文を元の URL / ファイルへ戻す記録。内部 hash や provider は通常 UI に出さない。 */
export interface SourceProvenance {
  canonical_locator?: string | null
  filename?: string | null
  external_id?: string | null
  fetched_at?: string | null
  ingested_at?: string | null
  adapter_version?: string | null
  provider?: string | null
  provider_model?: string | null
  original_content_hash?: string | null
  mime_type?: string | null
  ingestion_version?: string | null
}

/** content 上の区間と、ページ・時刻・話者。 */
export interface SourceSegment {
  normalized_start: number
  normalized_end: number
  page_number?: number | null
  start_seconds?: number | null
  end_seconds?: number | null
  speaker?: string | null
  timestamp?: string | null
  external_locator?: string | null
}

export interface SourceDocument {
  id: string
  source_type: SourceType | string
  title: string
  content: string
  language: string
  created_at: string
  metadata: Record<string, unknown>
  content_hash?: string | null
  ingestion_version?: string | null
  provenance?: SourceProvenance | null
  segments?: SourceSegment[]
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

export type IngestAction = 'create' | 'reuse' | 'append_version'

export interface IngestSourceResponse {
  action: IngestAction
  created: boolean
  source: SourceDocument
}

export interface IngestTextFields {
  title?: string
  note?: string
  language?: string
}

export interface IngestUrlInput extends IngestTextFields {
  url: string
}

export interface IngestVideoInput extends IngestTextFields {
  video: string
}

export interface IngestFileInput extends IngestTextFields {
  file: File
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

export interface FetchReviewQueueOptions {
  limit?: number
}

export interface ReviewQueueSummary {
  total_due: number
  recognition_due: number
  production_due: number
  overdue_count: number
}

export interface MasteryStats {
  attempt_count: number
  correct_count: number
  incorrect_count: number
  consecutive_correct: number
  last_reviewed_at: string | null
  mastery_score: number
}

export interface LearnerState extends MasteryStats {
  learning_item_id: string
  by_direction?: Partial<Record<SkillDirection, MasteryStats>>
}

export interface ReviewSchedule {
  learning_item_id: string
  skill_direction: SkillDirection
  due_at: string
  interval_days: number
  review_count: number
  lapse_count: number
  scheduler_version: string
  metadata?: Record<string, unknown>
}

export interface ReviewQueueEntry {
  item: LearningItem
  skill_direction: SkillDirection
  learner_state: LearnerState | null
  review_schedule: ReviewSchedule
  overdue_seconds: number
  overdue_days: number
  available_exercise_types: ExerciseType[]
}

export interface ReviewQueue {
  entries: ReviewQueueEntry[]
  summary: ReviewQueueSummary
}

export interface CreateReviewSessionInput {
  question_count?: number
  seed?: string
}

export interface SkippedReviewEntry {
  learning_item_id: string
  skill_direction: SkillDirection
  skip_reason: string
  detail?: string | null
}

export interface ReviewPracticeSession {
  session_id: string
  exercises: ExerciseView[]
  skipped_entries: SkippedReviewEntry[]
  requested_count: number
  generated_count: number
}

export type TutorSessionKind = 'practice' | 'review' | 'today'

export type ActivityKind = 'review' | 'new_practice'

export type ReasonCode =
  | 'OVERDUE_REVIEW'
  | 'RECENT_ERROR'
  | 'PRODUCTION_WEAKER'
  | 'RECOGNITION_WEAKER'
  | 'LOW_MASTERY'
  | 'LAPSE_RISK'
  | 'RECENT_SOURCE'
  | 'LEVEL_FIT'
  | 'HIGH_INTEREST'
  | 'HIGH_IMPORTANCE'

export interface TodayPlanEntryView {
  learning_item_id: string
  canonical_form: string
  meaning_ja: string
  item_type: LearningItemType
  activity_kind: ActivityKind
  skill_direction: SkillDirection
  selected_exercise_type: ExerciseType
  reason_codes: ReasonCode[]
  explanation: string
  source_titles: string[]
}

export interface TodayLearningPlanView {
  generated_at: string
  requested_count: number
  total_count: number
  review_count: number
  new_count: number
  deferred_due_count: number
  entries: TodayPlanEntryView[]
  summary_reason_codes: ReasonCode[]
  policy_version: string
  explanation_summary: string
}

export interface FetchTodayPlanOptions {
  question_count?: number
  max_new_count?: number
}

export interface CreateTodaySessionInput {
  question_count?: number
  max_new_count?: number
  seed?: string
}

export interface SkippedTodayEntry {
  learning_item_id: string
  skill_direction: SkillDirection
  activity_kind: ActivityKind
  skip_reason: string
  detail?: string | null
  exercise_skip_reason?: string | null
}

export interface TodayLearningSession {
  session_id: string
  exercises: ExerciseView[]
  entries: TodayPlanEntryView[]
  skipped_entries: SkippedTodayEntry[]
  requested_count: number
  generated_count: number
  review_count: number
  new_count: number
  deferred_due_count: number
  explanation_summary: string
  policy_version: string
  generated_at: string
  summary_reason_codes: ReasonCode[]
}

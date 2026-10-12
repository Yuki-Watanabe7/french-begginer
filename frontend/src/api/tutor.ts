import type {
  AcceptCandidateResponse,
  CreatePracticeSessionInput,
  CreateReviewSessionInput,
  CreateTodaySessionInput,
  CreateTutorSourceInput,
  ExerciseFeedback,
  IngestFileInput,
  IngestSourceResponse,
  IngestUrlInput,
  IngestVideoInput,
  ExerciseType,
  ExtractCandidatesResponse,
  FetchReviewQueueOptions,
  FetchTodayPlanOptions,
  FetchTutorItemsOptions,
  FetchTutorSourcesOptions,
  LearningItem,
  LearningItemCandidate,
  PracticeSession,
  ReviewPracticeSession,
  ReviewQueue,
  SourceDocument,
  SourceSummary,
  TodayLearningPlanView,
  TodayLearningSession,
} from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body?: unknown) {
    super(`API error: ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export function isNotFoundError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404
}

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw await apiErrorFromResponse(res)
  }
  return res.json() as Promise<T>
}

async function apiErrorFromResponse(res: Response): Promise<ApiError> {
  let body: unknown
  try {
    body = await res.json()
  } catch {
    body = undefined
  }
  return new ApiError(res.status, body)
}

export async function createTutorSource(
  input: CreateTutorSourceInput,
): Promise<SourceDocument> {
  return parseJson(
    await fetch(`${BASE}/api/tutor/sources`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: input.title,
        content: input.content,
        language: input.language ?? 'fr',
        metadata: input.metadata ?? {},
      }),
    }),
  )
}

function readIngestedSource(payload: IngestSourceResponse): SourceDocument {
  if (!payload?.source) {
    throw new Error('ingest response missing source')
  }
  return payload.source
}

function ingestJsonBody(fields: {
  title?: string
  note?: string
  language?: string
}): Record<string, string> {
  const body: Record<string, string> = {
    language: fields.language?.trim() || 'fr',
  }
  const title = fields.title?.trim()
  const note = fields.note?.trim()
  if (title) body.title = title
  if (note) body.note = note
  return body
}

async function postIngestJson(
  path: string,
  body: Record<string, string>,
): Promise<SourceDocument> {
  return readIngestedSource(
    await parseJson<IngestSourceResponse>(
      await fetch(`${BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    ),
  )
}

function ingestFormData(input: IngestFileInput): FormData {
  const form = new FormData()
  form.append('file', input.file, input.file.name)
  const title = input.title?.trim()
  const note = input.note?.trim()
  if (title) form.append('title', title)
  if (note) form.append('note', note)
  form.append('language', input.language?.trim() || 'fr')
  return form
}

async function postIngestFile(path: string, input: IngestFileInput): Promise<SourceDocument> {
  return readIngestedSource(
    await parseJson<IngestSourceResponse>(
      await fetch(`${BASE}${path}`, {
        method: 'POST',
        body: ingestFormData(input),
      }),
    ),
  )
}

export async function ingestTutorUrl(input: IngestUrlInput): Promise<SourceDocument> {
  return postIngestJson('/api/tutor/sources/ingest/url', {
    ...ingestJsonBody(input),
    url: input.url.trim(),
  })
}

export async function ingestTutorPdf(input: IngestFileInput): Promise<SourceDocument> {
  return postIngestFile('/api/tutor/sources/ingest/pdf', input)
}

export async function ingestTutorYoutube(input: IngestVideoInput): Promise<SourceDocument> {
  return postIngestJson('/api/tutor/sources/ingest/youtube', {
    ...ingestJsonBody(input),
    video: input.video.trim(),
  })
}

export async function ingestTutorSubtitle(input: IngestFileInput): Promise<SourceDocument> {
  return postIngestFile('/api/tutor/sources/ingest/subtitle', input)
}

export async function ingestTutorTextFile(input: IngestFileInput): Promise<SourceDocument> {
  return postIngestFile('/api/tutor/sources/ingest/text-file', input)
}

export async function ingestTutorConversation(input: IngestFileInput): Promise<SourceDocument> {
  return postIngestFile('/api/tutor/sources/ingest/conversation', input)
}

/** 音声文字起こし API（Issue #193）。未設定や未配備の 404 / 501 は呼び出し側が案内する。 */
export async function ingestTutorAudio(input: IngestFileInput): Promise<SourceDocument> {
  return postIngestFile('/api/tutor/sources/ingest/audio', input)
}

export async function fetchTutorSources(
  options: FetchTutorSourcesOptions = {},
): Promise<SourceSummary[]> {
  const params = new URLSearchParams()
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit))
  }
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return parseJson(await fetch(`${BASE}/api/tutor/sources${query}`))
}

export async function fetchTutorSource(sourceId: string): Promise<SourceDocument> {
  return parseJson(
    await fetch(`${BASE}/api/tutor/sources/${encodeURIComponent(sourceId)}`),
  )
}

export async function extractCandidates(
  sourceId: string,
): Promise<ExtractCandidatesResponse> {
  return parseJson(
    await fetch(
      `${BASE}/api/tutor/sources/${encodeURIComponent(sourceId)}/candidates/extract`,
      { method: 'POST' },
    ),
  )
}

export async function fetchCandidates(
  sourceId: string,
): Promise<LearningItemCandidate[]> {
  return parseJson(
    await fetch(
      `${BASE}/api/tutor/sources/${encodeURIComponent(sourceId)}/candidates`,
    ),
  )
}

export async function acceptCandidate(
  candidateId: string,
): Promise<AcceptCandidateResponse> {
  return parseJson(
    await fetch(
      `${BASE}/api/tutor/candidates/${encodeURIComponent(candidateId)}/accept`,
      { method: 'POST' },
    ),
  )
}

export async function rejectCandidate(
  candidateId: string,
): Promise<LearningItemCandidate> {
  return parseJson(
    await fetch(
      `${BASE}/api/tutor/candidates/${encodeURIComponent(candidateId)}/reject`,
      { method: 'POST' },
    ),
  )
}

export async function fetchTutorItems(
  options: FetchTutorItemsOptions = {},
): Promise<LearningItem[]> {
  const params = new URLSearchParams()
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit))
  }
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return parseJson(await fetch(`${BASE}/api/tutor/items${query}`))
}

export async function fetchTutorItem(itemId: string): Promise<LearningItem> {
  const detail = await parseJson<{ item: LearningItem }>(
    await fetch(`${BASE}/api/tutor/items/${encodeURIComponent(itemId)}`),
  )
  return detail.item
}

export async function fetchReviewQueue(
  options: FetchReviewQueueOptions = {},
): Promise<ReviewQueue> {
  const params = new URLSearchParams()
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit))
  }
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return parseJson(await fetch(`${BASE}/api/tutor/reviews/queue${query}`))
}

export async function createReviewSession(
  input: CreateReviewSessionInput = {},
): Promise<ReviewPracticeSession> {
  const body: Record<string, unknown> = {}
  if (input.question_count !== undefined) body.question_count = input.question_count
  if (input.seed !== undefined) body.seed = input.seed
  return parseJson(
    await fetch(`${BASE}/api/tutor/review/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function fetchTodayPlan(
  options: FetchTodayPlanOptions = {},
): Promise<TodayLearningPlanView> {
  const params = new URLSearchParams()
  if (options.question_count !== undefined) {
    params.set('question_count', String(options.question_count))
  }
  if (options.max_new_count !== undefined) {
    params.set('max_new_count', String(options.max_new_count))
  }
  const query = params.size > 0 ? `?${params.toString()}` : ''
  return parseJson(await fetch(`${BASE}/api/tutor/today${query}`))
}

export async function createTodaySession(
  input: CreateTodaySessionInput = {},
): Promise<TodayLearningSession> {
  const body: Record<string, unknown> = {}
  if (input.question_count !== undefined) body.question_count = input.question_count
  if (input.max_new_count !== undefined) body.max_new_count = input.max_new_count
  if (input.seed !== undefined) body.seed = input.seed
  return parseJson(
    await fetch(`${BASE}/api/tutor/today/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function createPracticeSession(
  input: CreatePracticeSessionInput = {},
): Promise<PracticeSession> {
  const body: Record<string, unknown> = {}
  if (input.source_id !== undefined) body.source_id = input.source_id
  if (input.item_ids !== undefined) body.item_ids = input.item_ids
  if (input.question_count !== undefined) body.question_count = input.question_count
  if (input.seed !== undefined) body.seed = input.seed
  return parseJson(
    await fetch(`${BASE}/api/tutor/practice/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

interface ExerciseAnswerApiResponse {
  correct: boolean
  correct_answer: string
  given: string | string[]
  explanation_ja?: string | null
  source_context?: string | null
}

export async function submitExerciseAnswer(
  itemId: string,
  exerciseType: ExerciseType,
  answer: string | string[],
  options: { id?: string } = {},
): Promise<ExerciseFeedback> {
  const body: Record<string, unknown> = { answer }
  if (options.id !== undefined) body.id = options.id
  const raw = await parseJson<ExerciseAnswerApiResponse>(
    await fetch(
      `${BASE}/api/tutor/items/${encodeURIComponent(itemId)}/exercises/${encodeURIComponent(exerciseType)}/answer`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),
  )
  return {
    correct: raw.correct,
    correct_answer: raw.correct_answer,
    given: raw.given,
    explanation_ja: raw.explanation_ja ?? null,
    source_context: raw.source_context ?? null,
    meaning_ja: null,
    canonical_form: null,
  }
}

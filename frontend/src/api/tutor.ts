import type {
  AcceptCandidateResponse,
  CreateTutorSourceInput,
  ExtractCandidatesResponse,
  FetchTutorSourcesOptions,
  LearningItemCandidate,
  SourceDocument,
  SourceSummary,
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

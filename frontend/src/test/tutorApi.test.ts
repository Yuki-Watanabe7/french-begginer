import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  ApiError,
  acceptCandidate,
  createTutorSource,
  extractCandidates,
  fetchCandidates,
  fetchTutorSource,
  fetchTutorSources,
  isNotFoundError,
  rejectCandidate,
} from '../api/tutor'
import { checkAnswer, fetchNextQuestion } from '../api/client'
import type { SourceDocument, SourceSummary } from '../types'

const SOURCE: SourceDocument = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  content: "Il s'agit d'un article.",
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  metadata: { origin: 'hand' },
}

const SUMMARY: SourceSummary = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  content_preview: "Il s'agit d'un article.",
}

function mockJsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response
}

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('createTutorSource', () => {
  it('POST /api/tutor/sources に title/content/language/metadata を送る', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(SOURCE, 201))

    const created = await createTutorSource({
      title: 'Le Monde',
      content: "Il s'agit d'un article.",
      language: 'fr',
      metadata: { origin: 'hand' },
    })

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith('/api/tutor/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Le Monde',
        content: "Il s'agit d'un article.",
        language: 'fr',
        metadata: { origin: 'hand' },
      }),
    })
    expect(created).toEqual(SOURCE)
  })

  it('language / metadata 未指定時は fr と空オブジェクトを送る', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(SOURCE, 201))

    await createTutorSource({ title: 't', content: 'c' })

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      '/api/tutor/sources',
      expect.objectContaining({
        body: JSON.stringify({
          title: 't',
          content: 'c',
          language: 'fr',
          metadata: {},
        }),
      }),
    )
  })
})

describe('fetchTutorSources', () => {
  it('GET /api/tutor/sources を呼ぶ', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse([SUMMARY]))

    const rows = await fetchTutorSources()

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith('/api/tutor/sources')
    expect(rows).toEqual([SUMMARY])
  })

  it('limit 指定時は query に載せる', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse([]))

    await fetchTutorSources({ limit: 2 })

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith('/api/tutor/sources?limit=2')
  })
})

describe('fetchTutorSource', () => {
  it('source id を URL encode して詳細を取得する', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(SOURCE))

    const sourceId = 'src/あ?x=1'
    const document = await fetchTutorSource(sourceId)

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      `/api/tutor/sources/${encodeURIComponent(sourceId)}`,
    )
    expect(document).toEqual(SOURCE)
  })
})

describe('Tutor API エラー処理', () => {
  it('non-2xx は reject し、404 は呼び出し側で判別できる', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockJsonResponse({ detail: 'SourceDocument not found: missing' }, 404),
    )

    const error = await fetchTutorSource('missing').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(isNotFoundError(error)).toBe(true)
    expect(error).toMatchObject({
      status: 404,
      body: { detail: 'SourceDocument not found: missing' },
    })
  })

  it('422 も成功値として返さない', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockJsonResponse({ detail: 'validation error' }, 422),
    )

    await expect(createTutorSource({ title: '', content: 'c' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
    })
  })

  it('成功レスポンスの JSON decode 失敗は握り潰さない', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError('Unexpected token')),
    } as Response)

    await expect(fetchTutorSources()).rejects.toThrow(SyntaxError)
  })
})

describe('既存 API client', () => {
  it('動詞問題取得の path は変わっていない', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockJsonResponse({ verb: 'parler', tense: 'présent', pronoun: 'je' }),
    )

    await fetchNextQuestion('er')

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith('/api/questions/next?group=er')
  })

  it('動詞回答チェックも non-2xx で reject する', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse({ detail: 'bad' }, 500))

    await expect(checkAnswer('parler', 'présent', 'je', 'parle')).rejects.toThrow('API error: 500')
  })
})

const CANDIDATE = {
  id: 'cand-1',
  source_document_id: 'src-1',
  item_type: 'expression',
  canonical_form: 'se rendre compte',
  meaning_ja: '〜に気づく',
  explanation_ja: null,
  level: 'A2',
  evidence_span: { start: 0, end: 5 },
  evidence_text: 'rendu',
  confidence: 0.8,
  status: 'candidate',
  extraction_version: 'extract-v1',
  created_at: '2026-08-24T12:00:00+00:00',
}

describe('extractCandidates', () => {
  it('POST /api/tutor/sources/:id/candidates/extract を呼ぶ', async () => {
    const body = {
      source_document_id: 'src/あ',
      extraction_version: 'extract-v1',
      created: [CANDIDATE],
      skipped: [],
    }
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(body))

    const sourceId = 'src/あ'
    const result = await extractCandidates(sourceId)

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      `/api/tutor/sources/${encodeURIComponent(sourceId)}/candidates/extract`,
      { method: 'POST' },
    )
    expect(result).toEqual(body)
  })
})

describe('fetchCandidates', () => {
  it('source id を URL encode して一覧を取得する', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse([CANDIDATE]))

    const sourceId = 'src/あ?x=1'
    const rows = await fetchCandidates(sourceId)

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      `/api/tutor/sources/${encodeURIComponent(sourceId)}/candidates`,
    )
    expect(rows).toEqual([CANDIDATE])
  })
})

describe('acceptCandidate / rejectCandidate', () => {
  it('accept は candidate と item を返し、id を encode する', async () => {
    const body = {
      candidate: { ...CANDIDATE, status: 'accepted' },
      item: { id: 'item-1' },
      merged: false,
    }
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(body))

    const candidateId = 'cand/あ'
    const result = await acceptCandidate(candidateId)

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      `/api/tutor/candidates/${encodeURIComponent(candidateId)}/accept`,
      { method: 'POST' },
    )
    expect(result).toEqual(body)
  })

  it('reject は更新後の candidate を返す', async () => {
    const body = { ...CANDIDATE, status: 'rejected' }
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockJsonResponse(body))

    const result = await rejectCandidate('cand-1')

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      '/api/tutor/candidates/cand-1/reject',
      { method: 'POST' },
    )
    expect(result.status).toBe('rejected')
  })

  it('503 は成功値として返さない', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockJsonResponse({ detail: 'OPENAI_API_KEY が設定されていない' }, 503),
    )

    await expect(extractCandidates('src-1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 503,
    })
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  ApiError,
  acceptCandidate,
  createTutorSource,
  extractCandidates,
  fetchCandidates,
  fetchReviewQueue,
  fetchTutorSource,
  fetchTutorSources,
  rejectCandidate,
} from '../api/tutor'
import type {
  AcceptCandidateResponse,
  CreateTutorSourceInput,
  ExtractCandidatesResponse,
  LearningItem,
  LearningItemCandidate,
  LearningItemType,
  SourceDocument,
  SourceSummary,
} from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchCandidates: vi.fn(),
    extractCandidates: vi.fn(),
    acceptCandidate: vi.fn(),
    rejectCandidate: vi.fn(),
    fetchReviewQueue: vi.fn(),
  }
})

const mockList = vi.mocked(fetchTutorSources)
const mockGet = vi.mocked(fetchTutorSource)
const mockCreate = vi.mocked(createTutorSource)
const mockFetchCandidates = vi.mocked(fetchCandidates)
const mockExtract = vi.mocked(extractCandidates)
const mockAccept = vi.mocked(acceptCandidate)
const mockReject = vi.mocked(rejectCandidate)
const mockQueue = vi.mocked(fetchReviewQueue)

const SOURCE_TITLE = 'Article test'
const SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
const SOURCE_NOTE = 'se rendre compte が気になった'
const PREVIEW_MAX = 120

type MemoryStore = {
  byId: Map<string, SourceDocument>
  candidates: Map<string, LearningItemCandidate[]>
  items: Map<string, LearningItem>
  seq: number
  itemSeq: number
}

function createStore(): MemoryStore {
  return {
    byId: new Map(),
    candidates: new Map(),
    items: new Map(),
    seq: 0,
    itemSeq: 0,
  }
}

function toSummary(document: SourceDocument): SourceSummary {
  return {
    id: document.id,
    source_type: document.source_type,
    title: document.title,
    language: document.language,
    created_at: document.created_at,
    content_preview: document.content.slice(0, PREVIEW_MAX),
  }
}

function fixtureCandidates(sourceId: string): LearningItemCandidate[] {
  const rows: Array<{
    item_type: LearningItemType
    canonical_form: string
    meaning_ja: string
    evidence_text: string
    explanation_ja: string | null
  }> = [
    {
      item_type: 'expression',
      canonical_form: 'se rendre compte de',
      meaning_ja: '〜に気づく',
      evidence_text: 'rendu compte',
      explanation_ja: 'よく出る表現',
    },
    {
      item_type: 'grammar',
      canonical_form: 'il fallait',
      meaning_ja: '〜しなければならなかった',
      evidence_text: 'il fallait',
      explanation_ja: '義務の過去',
    },
    {
      item_type: 'vocabulary',
      canonical_form: 'stratégie',
      meaning_ja: '戦略',
      evidence_text: 'stratégie',
      explanation_ja: null,
    },
    {
      item_type: 'conjugation',
      canonical_form: 'changer',
      meaning_ja: '変える',
      evidence_text: 'changer',
      explanation_ja: null,
    },
  ]
  return rows.map((row, index) => ({
    id: `cand-${index + 1}`,
    source_document_id: sourceId,
    item_type: row.item_type,
    canonical_form: row.canonical_form,
    meaning_ja: row.meaning_ja,
    explanation_ja: row.explanation_ja,
    level: 'A2',
    evidence_span: { start: index, end: index + 4 },
    evidence_text: row.evidence_text,
    confidence: 0.9 - index * 0.05,
    status: 'candidate',
    extraction_version: 'extract-v1',
    created_at: '2026-08-24T12:00:00.000Z',
  }))
}

function bindMemoryApi(store: MemoryStore) {
  mockCreate.mockImplementation(async (input: CreateTutorSourceInput) => {
    store.seq += 1
    const document: SourceDocument = {
      id: `src-${store.seq}`,
      source_type: 'manual_text',
      title: input.title,
      content: input.content,
      language: input.language ?? 'fr',
      created_at: new Date(Date.UTC(2026, 7, 23, 12, 0, store.seq)).toISOString(),
      metadata: input.metadata ?? {},
    }
    store.byId.set(document.id, document)
    store.candidates.set(document.id, [])
    return document
  })
  mockList.mockImplementation(async () =>
    [...store.byId.values()]
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || a.id.localeCompare(b.id))
      .map(toSummary),
  )
  mockGet.mockImplementation(async (sourceId: string) => {
    const document = store.byId.get(sourceId)
    if (!document) {
      throw new ApiError(404, { detail: `SourceDocument not found: ${sourceId}` })
    }
    return document
  })
  mockFetchCandidates.mockImplementation(async (sourceId: string) => {
    return [...(store.candidates.get(sourceId) ?? [])]
  })
  mockExtract.mockImplementation(async (sourceId: string): Promise<ExtractCandidatesResponse> => {
    const existing = store.candidates.get(sourceId) ?? []
    if (existing.length > 0) {
      return {
        source_document_id: sourceId,
        extraction_version: 'extract-v1',
        created: [],
        skipped: existing,
      }
    }
    const created = fixtureCandidates(sourceId)
    store.candidates.set(sourceId, created)
    return {
      source_document_id: sourceId,
      extraction_version: 'extract-v1',
      created,
      skipped: [],
    }
  })
  mockAccept.mockImplementation(async (candidateId: string): Promise<AcceptCandidateResponse> => {
    for (const [sourceId, rows] of store.candidates) {
      const index = rows.findIndex(row => row.id === candidateId)
      if (index < 0) continue
      const updated: LearningItemCandidate = { ...rows[index], status: 'accepted' }
      const next = [...rows]
      next[index] = updated
      store.candidates.set(sourceId, next)
      store.itemSeq += 1
      const item: LearningItem = {
        id: `item-${store.itemSeq}`,
        item_type: updated.item_type,
        canonical_form: updated.canonical_form,
        meaning_ja: updated.meaning_ja,
        explanation_ja: updated.explanation_ja,
        level: updated.level,
        source_refs: [
          {
            source_document_id: sourceId,
            evidence_span: updated.evidence_span,
            confidence: updated.confidence,
          },
        ],
        status: 'active',
        created_at: '2026-08-24T12:30:00.000Z',
      }
      store.items.set(item.id, item)
      return { candidate: updated, item, merged: false }
    }
    throw new ApiError(404, { detail: `LearningItemCandidate not found: ${candidateId}` })
  })
  mockReject.mockImplementation(async (candidateId: string) => {
    for (const [sourceId, rows] of store.candidates) {
      const index = rows.findIndex(row => row.id === candidateId)
      if (index < 0) continue
      const updated: LearningItemCandidate = { ...rows[index], status: 'rejected' }
      const next = [...rows]
      next[index] = updated
      store.candidates.set(sourceId, next)
      return updated
    }
    throw new ApiError(404, { detail: `LearningItemCandidate not found: ${candidateId}` })
  })
  mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function saveFixtureSource() {
  await userEvent.click(screen.getByRole('button', { name: '新しいテキストを追加' }))
  await userEvent.type(screen.getByLabelText(/タイトル/), SOURCE_TITLE)
  await userEvent.type(screen.getByLabelText(/本文/), SOURCE_CONTENT)
  await userEvent.type(screen.getByLabelText(/メモ/), SOURCE_NOTE)
  await userEvent.click(screen.getByRole('button', { name: '保存する' }))
  await screen.findByRole('heading', { name: SOURCE_TITLE })
}

describe('Tutor Phase 2 vertical slice', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
  })

  it('抽出から根拠確認・採用・却下・再表示まで一本でつながる', async () => {
    const store = createStore()
    bindMemoryApi(store)

    const { unmount } = render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('まだ保存したテキストがありません')
    await saveFixtureSource()

    expect(
      screen.getByText('まだ学習候補がありません。抽出すると、覚える候補を確認できます'),
    ).toBeInTheDocument()
    const extractBtn = screen.getByRole('button', { name: '学習候補を抽出' })
    expect(extractBtn).toHaveStyle({ width: '100%', minHeight: '48px' })

    await userEvent.click(extractBtn)
    await screen.findByText('4件の新しい候補を抽出しました')
    expect(screen.getByText('表現')).toBeInTheDocument()
    expect(screen.getByText('文法')).toBeInTheDocument()
    expect(screen.getByText('語彙')).toBeInTheDocument()
    expect(screen.getByText('活用')).toBeInTheDocument()
    expect(
      screen.getByRole('article', { name: '表現 se rendre compte de' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '文法 il fallait' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '語彙 stratégie' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '活用 changer' })).toBeInTheDocument()
    expect(screen.getByText('rendu compte')).toBeInTheDocument()
    expect(screen.queryByText(/metadata/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/openai/i)).not.toBeInTheDocument()

    const expressionCard = screen.getByRole('article', {
      name: '表現 se rendre compte de',
    })
    expect(within(expressionCard).getByText('〜に気づく')).toBeInTheDocument()
    expect(within(expressionCard).getByText('rendu compte')).toBeInTheDocument()
    const acceptBtn = within(expressionCard).getByRole('button', { name: '採用する' })
    const rejectBtn = within(expressionCard).getByRole('button', { name: '却下する' })
    expect(acceptBtn).toHaveStyle({ minHeight: '44px' })
    expect(rejectBtn).toHaveStyle({ minHeight: '44px' })
    expect(expressionCard).toHaveStyle({ overflowWrap: 'anywhere' })

    await userEvent.click(acceptBtn)
    await within(expressionCard).findByText('採用済み')
    expect(
      within(expressionCard).queryByRole('button', { name: '採用する' }),
    ).not.toBeInTheDocument()

    const vocabCard = screen.getByRole('article', { name: '語彙 stratégie' })
    await userEvent.click(within(vocabCard).getByRole('button', { name: '却下する' }))
    await within(vocabCard).findByText('却下')
    expect(vocabCard).toBeInTheDocument()
    expect(store.items.size).toBe(1)
    expect([...store.items.values()][0].canonical_form).toBe('se rendre compte de')
    expect(
      [...store.candidates.get('src-1') ?? []].filter(row => row.status === 'rejected'),
    ).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    const listButton = await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
    await userEvent.click(listButton)
    await screen.findByRole('heading', { name: SOURCE_TITLE })
    expect(await screen.findByText('se rendre compte de')).toBeInTheDocument()
    expect(screen.getAllByText('採用済み').length).toBeGreaterThan(0)
    expect(screen.getAllByText('却下').length).toBeGreaterThan(0)
    expect(screen.getAllByText('未確認').length).toBeGreaterThan(0)

    await userEvent.click(screen.getByRole('button', { name: 'もう一度抽出する' }))
    await screen.findByText('新しい候補はありません。既存の候補を表示しています')
    expect(screen.getByText('se rendre compte de')).toBeInTheDocument()
    expect(screen.getAllByText('採用済み').length).toBeGreaterThan(0)
    expect(screen.getAllByText('却下').length).toBeGreaterThan(0)
    expect(store.candidates.get('src-1')).toHaveLength(4)
    expect(store.items.size).toBe(1)

    unmount()
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) }))
    await screen.findByRole('heading', { name: SOURCE_TITLE })
    await screen.findByRole('article', { name: '表現 se rendre compte de' })
    expect(screen.getAllByText('採用済み').length).toBeGreaterThan(0)
    expect(screen.getAllByText('却下').length).toBeGreaterThan(0)
    expect(screen.getByRole('article', { name: '文法 il fallait' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: '活用 changer' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
  })

  it('候補の loading / error / empty を扱う', async () => {
    const store = createStore()
    bindMemoryApi(store)
    mockFetchCandidates.mockImplementationOnce(() => new Promise(() => {}))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    expect(screen.getByText('学習候補を読み込み中...')).toBeInTheDocument()
  })

  it('候補一覧の取得失敗から再試行できる', async () => {
    const store = createStore()
    bindMemoryApi(store)
    mockFetchCandidates
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockImplementation(async (sourceId: string) => [...(store.candidates.get(sourceId) ?? [])])

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByText('まだ学習候補がありません。抽出すると、覚える候補を確認できます')
  })

  it('抽出 0 件と抽出失敗を扱い、既存 Source 一覧へ戻れる', async () => {
    const store = createStore()
    bindMemoryApi(store)
    mockExtract
      .mockResolvedValueOnce({
        source_document_id: 'src-1',
        extraction_version: 'extract-v1',
        created: [],
        skipped: [],
      })
      .mockRejectedValueOnce(
        new ApiError(503, { detail: 'OPENAI_API_KEY が設定されていない' }),
      )

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    await userEvent.click(screen.getByRole('button', { name: '学習候補を抽出' }))
    await screen.findByText('学習候補は見つかりませんでした')

    await userEvent.click(screen.getByRole('button', { name: 'もう一度抽出する' }))
    await screen.findByText(
      '学習候補の抽出に必要な設定がありません。管理者に連絡してください',
    )

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
  })

  it('抽出中は多重実行せず、完了後に候補を表示する', async () => {
    const store = createStore()
    bindMemoryApi(store)
    const pending = deferred<ExtractCandidatesResponse>()
    mockExtract.mockReturnValueOnce(pending.promise)

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    await userEvent.click(screen.getByRole('button', { name: '学習候補を抽出' }))
    expect(screen.getByRole('button', { name: '抽出しています...' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '抽出しています...' }))
    expect(mockExtract).toHaveBeenCalledTimes(1)

    const created = fixtureCandidates('src-1')
    store.candidates.set('src-1', created)
    pending.resolve({
      source_document_id: 'src-1',
      extraction_version: 'extract-v1',
      created,
      skipped: [],
    })
    await screen.findByText('se rendre compte de')
    expect(screen.getByText('4件の新しい候補を抽出しました')).toBeInTheDocument()
  })

  it('Tutor からモード選択へ戻り、既存クイズ入口が残っている', async () => {
    bindMemoryApi(createStore())
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('まだ保存したテキストがありません')
    await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
    expect(screen.getByText('練習モードを選択')).toBeInTheDocument()
    expect(screen.getByText('動詞活用練習')).toBeInTheDocument()
    expect(screen.getByText('名詞の性クイズ')).toBeInTheDocument()
    expect(screen.getByText('冠詞付き名詞')).toBeInTheDocument()
    expect(screen.getByText('自分の教材')).toBeInTheDocument()
  })
})

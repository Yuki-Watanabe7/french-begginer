import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  ApiError,
  createTutorSource,
  fetchTutorSource,
  fetchTutorSources,
} from '../api/tutor'
import type { CreateTutorSourceInput, SourceDocument, SourceSummary } from '../types'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
  }
})

const mockList = vi.mocked(fetchTutorSources)
const mockGet = vi.mocked(fetchTutorSource)
const mockCreate = vi.mocked(createTutorSource)

const SOURCE_TITLE = 'Article test'
const SOURCE_CONTENT = "Je me suis rendu compte qu'il fallait changer de stratégie."
const SOURCE_NOTE = 'se rendre compte が気になった'
const PREVIEW_MAX = 120

type MemoryStore = {
  byId: Map<string, SourceDocument>
  seq: number
}

function createStore(): MemoryStore {
  return { byId: new Map(), seq: 0 }
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
}

async function enterTutor() {
  render(<App />)
  await userEvent.click(screen.getByText('自分の教材'))
}

describe('Tutor Phase 1 vertical slice', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('貼り付け保存から一覧・詳細・再読み込みまで一本でつながる', async () => {
    const store = createStore()
    bindMemoryApi(store)

    const { unmount } = render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('まだ保存したテキストがありません')

    await userEvent.click(screen.getByRole('button', { name: '新しいテキストを追加' }))
    expect(screen.getByLabelText(/本文/)).toHaveStyle({ minHeight: '40vh' })
    expect(screen.getByRole('button', { name: '保存する' })).toHaveStyle({ width: '100%' })

    await userEvent.click(screen.getByRole('button', { name: '保存する' }))
    expect(mockCreate).not.toHaveBeenCalled()
    expect(screen.getByText('タイトルを入力してください')).toBeInTheDocument()
    expect(screen.getByText('フランス語の本文を入力してください')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/タイトル/), SOURCE_TITLE)
    await userEvent.type(screen.getByLabelText(/本文/), SOURCE_CONTENT)
    await userEvent.type(screen.getByLabelText(/メモ/), SOURCE_NOTE)
    await userEvent.click(screen.getByRole('button', { name: '保存する' }))

    await screen.findByText('保存しました')
    expect(screen.getByRole('heading', { name: SOURCE_TITLE })).toBeInTheDocument()
    expect(screen.getByText(SOURCE_NOTE)).toBeInTheDocument()
    expect(document.querySelector('[lang="fr"]')?.textContent).toBe(SOURCE_CONTENT)
    expect(document.querySelector('[lang="fr"]')).toHaveStyle({
      overflowWrap: 'anywhere',
      whiteSpace: 'pre-wrap',
    })
    expect(screen.queryByText(/抽出/)).not.toBeInTheDocument()
    expect(screen.queryByText(/LearningItem/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    const listButton = await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
    expect(listButton).toHaveTextContent(SOURCE_CONTENT)
    expect(screen.queryByText(SOURCE_NOTE)).not.toBeInTheDocument()

    await userEvent.click(listButton)
    await screen.findByRole('heading', { name: SOURCE_TITLE })
    expect(mockGet).toHaveBeenCalledWith('src-1')
    expect(screen.getByText(SOURCE_NOTE)).toBeInTheDocument()
    expect(document.querySelector('[lang="fr"]')?.textContent).toBe(SOURCE_CONTENT)

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })

    unmount()
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
    await userEvent.click(screen.getByRole('button', { name: new RegExp(SOURCE_TITLE) }))
    await screen.findByRole('heading', { name: SOURCE_TITLE })
    expect(screen.getByText(SOURCE_NOTE)).toBeInTheDocument()
    expect(document.querySelector('[lang="fr"]')?.textContent).toBe(SOURCE_CONTENT)
  })

  it('一覧の loading / error と詳細の 404 を扱う', async () => {
    mockList.mockImplementationOnce(() => new Promise(() => {}))
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    expect(screen.getByText('読み込み中...')).toBeInTheDocument()
  })

  it('一覧取得失敗から再試行できる', async () => {
    const store = createStore()
    mockList
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockImplementation(async () => [...store.byId.values()].map(toSummary))
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByText('まだ保存したテキストがありません')
  })

  it('詳細が 404 のときは見つからないと表示する', async () => {
    const summary: SourceSummary = {
      id: 'missing',
      source_type: 'manual_text',
      title: SOURCE_TITLE,
      language: 'fr',
      created_at: '2026-08-23T12:00:00.000Z',
      content_preview: SOURCE_CONTENT,
    }
    mockList.mockResolvedValue([summary])
    mockGet.mockRejectedValue(new ApiError(404, { detail: 'missing' }))
    await enterTutor()
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) }))
    await screen.findByText('Sourceが見つかりません')
    expect(screen.queryByRole('button', { name: '再試行' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('button', { name: new RegExp(SOURCE_TITLE) })
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

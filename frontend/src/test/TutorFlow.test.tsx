import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorFlow } from '../components/TutorFlow'
import {
  createTutorSource,
  fetchCandidates,
  fetchReviewQueue,
  fetchTutorSource,
  fetchTutorSources,
} from '../api/tutor'
import type { SourceDocument, SourceSummary } from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchCandidates: vi.fn(),
    fetchReviewQueue: vi.fn(),
  }
})

const mockList = vi.mocked(fetchTutorSources)
const mockGet = vi.mocked(fetchTutorSource)
const mockCreate = vi.mocked(createTutorSource)
const mockFetchCandidates = vi.mocked(fetchCandidates)
const mockQueue = vi.mocked(fetchReviewQueue)

const SUMMARY: SourceSummary = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  content_preview: "Il s'agit d'un article.",
}

const SOURCE: SourceDocument = {
  ...SUMMARY,
  content: "Il s'agit d'un article.\n\nSuite.",
  metadata: { note: '新聞の社説' },
}

describe('TutorFlow', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchCandidates.mockResolvedValue([])
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
  })

  it('一覧から新規追加画面へ進み、一覧へ戻れる', async () => {
    mockList.mockResolvedValue([])
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: '新しいテキストを追加' }))
    expect(screen.getByLabelText(/タイトル/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByText('まだ保存したテキストがありません')
  })

  it('一覧から詳細を開き、原文を読んで一覧へ戻れる', async () => {
    mockList.mockResolvedValue([SUMMARY])
    mockGet.mockResolvedValue(SOURCE)
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: /Le Monde/ }))
    await screen.findByRole('heading', { name: 'Le Monde' })
    expect(document.querySelector('[lang="fr"]')?.textContent).toBe(SOURCE.content)
    expect(screen.getByText('新聞の社説')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('button', { name: /Le Monde/ })
  })

  it('保存成功後は詳細画面を再利用する', async () => {
    mockList.mockResolvedValue([])
    mockCreate.mockResolvedValue(SOURCE)
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: '新しいテキストを追加' }))
    await userEvent.type(screen.getByLabelText(/タイトル/), 'Le Monde')
    await userEvent.type(screen.getByLabelText(/本文/), "Il s'agit d'un article.")
    await userEvent.click(screen.getByRole('button', { name: '保存する' }))

    await screen.findByText('保存しました')
    expect(screen.getByRole('heading', { name: 'Le Monde' })).toBeInTheDocument()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('Tutor 画面からモード選択へ戻れる', async () => {
    mockList.mockResolvedValue([])
    const onBack = vi.fn()
    render(<TutorFlow onBack={onBack} />)

    await screen.findByText('まだ保存したテキストがありません')
    await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('一覧の学習するから出題数選択へ進める', async () => {
    mockList.mockResolvedValue([SUMMARY])
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: '学習する' }))
    expect(screen.getByText('出題数を選択')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('button', { name: /Le Monde/ })
  })

  it('Source詳細の学習するから練習設定へ進める', async () => {
    mockList.mockResolvedValue([SUMMARY])
    mockGet.mockResolvedValue(SOURCE)
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: /Le Monde/ }))
    await screen.findByRole('heading', { name: 'Le Monde' })
    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    expect(screen.getByText('出題数を選択')).toBeInTheDocument()
  })

  it('今日の復習から出題数選択へ進める', async () => {
    mockList.mockResolvedValue([SUMMARY])
    mockQueue.mockResolvedValue({
      entries: [],
      summary: {
        total_due: 3,
        recognition_due: 1,
        production_due: 2,
        overdue_count: 0,
      },
    })
    render(<TutorFlow onBack={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: '復習を始める' }))
    expect(screen.getByText('出題数を選択')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('button', { name: '復習を始める' })
    expect(screen.getByRole('button', { name: '学習する' })).toBeInTheDocument()
  })
})

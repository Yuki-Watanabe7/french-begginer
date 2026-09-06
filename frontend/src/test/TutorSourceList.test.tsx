import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorSourceList } from '../components/TutorSourceList'
import { ApiError, fetchReviewQueue, fetchTodayPlan, fetchTutorSources } from '../api/tutor'
import { formatTutorDateTime } from '../utils/tutor'
import type { SourceSummary } from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'
import { EMPTY_TODAY_PLAN } from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchReviewQueue: vi.fn(),
    fetchTodayPlan: vi.fn(),
  }
})

const mockList = vi.mocked(fetchTutorSources)
const mockQueue = vi.mocked(fetchReviewQueue)
const mockPlan = vi.mocked(fetchTodayPlan)

const NEWER: SourceSummary = {
  id: 'src-new',
  source_type: 'manual_text',
  title: 'Le Figaro',
  language: 'fr',
  created_at: '2026-08-23T14:00:00+00:00',
  content_preview: 'article récent',
}

const OLDER: SourceSummary = {
  id: 'src-old',
  source_type: 'manual_text',
  title: 'Le Monde',
  language: 'fr',
  created_at: '2026-08-22T12:00:00+00:00',
  content_preview: "Il s'agit d'un article.",
}

const LONG_TITLE: SourceSummary = {
  id: 'src-long',
  source_type: 'manual_text',
  title: 'Un très très long titre de source qui ne doit pas casser la mise en page mobile',
  language: 'fr',
  created_at: '2026-08-21T09:00:00+00:00',
  content_preview: 'preview',
}

describe('TutorSourceList', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
  })

  it('loading 表示をする', () => {
    mockList.mockImplementation(() => new Promise(() => {}))
    render(
      <TutorSourceList onSelect={() => {}} onAdd={() => {}} onBack={() => {}} />,
    )
    expect(screen.getByText('読み込み中...')).toBeInTheDocument()
  })

  it('0件時に empty state と追加導線を出す', async () => {
    mockList.mockResolvedValueOnce([])
    const onAdd = vi.fn()
    render(
      <TutorSourceList onSelect={() => {}} onAdd={onAdd} onBack={() => {}} />,
    )

    await screen.findByText('まだ保存したテキストがありません')
    await userEvent.click(screen.getByRole('button', { name: '新しいテキストを追加' }))
    expect(onAdd).toHaveBeenCalledTimes(1)
  })

  it('複数 Source の title を新しい順のまま表示する', async () => {
    mockList.mockResolvedValueOnce([NEWER, OLDER])
    render(
      <TutorSourceList onSelect={() => {}} onAdd={() => {}} onBack={() => {}} />,
    )

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('Le Figaro')).toBeInTheDocument()
    expect(within(items[1]).getByText('Le Monde')).toBeInTheDocument()
    expect(screen.getByText(formatTutorDateTime(NEWER.created_at))).toBeInTheDocument()
    expect(screen.getByText('article récent')).toBeInTheDocument()
  })

  it('Source 選択で詳細へ進む', async () => {
    mockList.mockResolvedValueOnce([NEWER, OLDER])
    const onSelect = vi.fn()
    render(
      <TutorSourceList onSelect={onSelect} onAdd={() => {}} onBack={() => {}} />,
    )

    await userEvent.click(await screen.findByRole('button', { name: /Le Figaro/ }))
    expect(onSelect).toHaveBeenCalledWith('src-new')
  })

  it('API error を表示し、再試行できる', async () => {
    mockList
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockResolvedValueOnce([OLDER])
    render(
      <TutorSourceList onSelect={() => {}} onAdd={() => {}} onBack={() => {}} />,
    )

    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByText('Le Monde')
  })

  it('長い title でも折り返す', async () => {
    mockList.mockResolvedValueOnce([LONG_TITLE])
    render(
      <TutorSourceList onSelect={() => {}} onAdd={() => {}} onBack={() => {}} />,
    )

    const title = await screen.findByText(LONG_TITLE.title)
    expect(title).toHaveStyle({ overflowWrap: 'anywhere' })
  })

  it('モード選択に戻れる', async () => {
    mockList.mockResolvedValueOnce([])
    const onBack = vi.fn()
    render(
      <TutorSourceList onSelect={() => {}} onAdd={() => {}} onBack={onBack} />,
    )

    await screen.findByText('まだ保存したテキストがありません')
    await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('学習する で全体練習を開始できる', async () => {
    mockList.mockResolvedValueOnce([NEWER])
    const onStartPractice = vi.fn()
    render(
      <TutorSourceList
        onSelect={() => {}}
        onAdd={() => {}}
        onBack={() => {}}
        onStartPractice={onStartPractice}
      />,
    )

    await userEvent.click(await screen.findByRole('button', { name: '学習する' }))
    expect(onStartPractice).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '学習する' })).toHaveStyle({
      width: '100%',
      minHeight: '48px',
    })
  })

  it('onStartReview があるとき今日の復習カードを出す', async () => {
    mockList.mockResolvedValueOnce([NEWER])
    const onStartReview = vi.fn()
    render(
      <TutorSourceList
        onSelect={() => {}}
        onAdd={() => {}}
        onBack={() => {}}
        onStartReview={onStartReview}
      />,
    )

    await screen.findByRole('heading', { name: '今日の復習' })
    expect(screen.getByText('今すぐ復習する項目はありません')).toBeInTheDocument()
  })

  it('onStartToday があるとき今日の学習カードを出す', async () => {
    mockList.mockResolvedValueOnce([NEWER])
    const onStartToday = vi.fn()
    render(
      <TutorSourceList
        onSelect={() => {}}
        onAdd={() => {}}
        onBack={() => {}}
        onStartToday={onStartToday}
      />,
    )

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByText('今日は学習できる項目がありません')).toBeInTheDocument()
  })
})

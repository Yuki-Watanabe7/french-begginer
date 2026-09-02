import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorTodayReviewCard } from '../components/TutorTodayReviewCard'
import { ApiError, fetchReviewQueue } from '../api/tutor'
import { EMPTY_REVIEW_QUEUE, reviewQueueFixture } from './reviewQueueFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchReviewQueue: vi.fn(),
  }
})

const mockQueue = vi.mocked(fetchReviewQueue)

describe('TutorTodayReviewCard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('due 0件なら empty state を出し、開始ボタンは出さない', async () => {
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    const onStartReview = vi.fn()
    render(<TutorTodayReviewCard onStartReview={onStartReview} />)

    await screen.findByText('今すぐ復習する項目はありません')
    expect(screen.queryByRole('button', { name: '復習を始める' })).not.toBeInTheDocument()
    expect(screen.queryByText('recognition')).not.toBeInTheDocument()
    expect(screen.queryByText('production')).not.toBeInTheDocument()
  })

  it('due件数と任意の direction / overdue を表示し、復習を開始できる', async () => {
    mockQueue.mockResolvedValue(
      reviewQueueFixture({
        total_due: 7,
        recognition_due: 4,
        production_due: 3,
        overdue_count: 2,
      }),
    )
    const onStartReview = vi.fn()
    render(<TutorTodayReviewCard onStartReview={onStartReview} />)

    await screen.findByText(/復習待ち/)
    expect(screen.getByTestId('due-count')).toHaveTextContent('7')
    expect(screen.getByText('期限を過ぎた復習 2件')).toBeInTheDocument()
    expect(screen.getByText('見て分かる練習 4件 / 自分で言う練習 3件')).toBeInTheDocument()
    expect(screen.queryByText(/recognition/)).not.toBeInTheDocument()
    expect(screen.queryByText(/production/)).not.toBeInTheDocument()

    const start = screen.getByRole('button', { name: '復習を始める' })
    expect(start).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(start)
    expect(onStartReview).toHaveBeenCalledTimes(1)
  })

  it('overdue が 0 なら期限切れ表示を出さない', async () => {
    mockQueue.mockResolvedValue(
      reviewQueueFixture({
        total_due: 3,
        recognition_due: 1,
        production_due: 2,
        overdue_count: 0,
      }),
    )
    render(<TutorTodayReviewCard onStartReview={() => {}} />)

    await screen.findByText(/復習待ち/)
    expect(screen.queryByText(/期限を過ぎた復習/)).not.toBeInTheDocument()
  })

  it('queue 取得失敗時は再試行できる', async () => {
    mockQueue
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockResolvedValueOnce(
        reviewQueueFixture({
          total_due: 1,
          recognition_due: 1,
          production_due: 0,
        }),
      )
    render(<TutorTodayReviewCard onStartReview={() => {}} />)

    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByRole('button', { name: '復習を始める' })
    expect(screen.getByTestId('due-count')).toHaveTextContent('1')
  })

  it('loading 中は件数を確定表示しない', () => {
    mockQueue.mockImplementation(() => new Promise(() => {}))
    render(<TutorTodayReviewCard onStartReview={() => {}} />)
    expect(screen.getByText('読み込み中...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '復習を始める' })).not.toBeInTheDocument()
  })
})

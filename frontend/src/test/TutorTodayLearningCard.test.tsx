import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorTodayLearningCard } from '../components/TutorTodayLearningCard'
import { ApiError, fetchTodayPlan } from '../api/tutor'
import { EMPTY_TODAY_PLAN, todayPlanFixture, todayPlanEntryFixture } from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTodayPlan: vi.fn(),
  }
})

const mockPlan = vi.mocked(fetchTodayPlan)

describe('TutorTodayLearningCard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('empty plan なら開始ボタンを出さない', async () => {
    mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
    render(<TutorTodayLearningCard onStartToday={() => {}} />)

    await screen.findByText('今日は学習できる項目がありません')
    expect(screen.queryByRole('button', { name: '学習を始める' })).not.toBeInTheDocument()
    expect(screen.queryByText('HIGH_INTEREST')).not.toBeInTheDocument()
    expect(screen.queryByText(/関心の高い/)).not.toBeInTheDocument()
    expect(screen.queryByText(/rank_score|0\.\d+/)).not.toBeInTheDocument()
  })

  it('review/new/deferred 件数と理由を表示し、学習を開始できる', async () => {
    mockPlan.mockResolvedValue(
      todayPlanFixture({
        review_count: 7,
        new_count: 3,
        deferred_due_count: 4,
        summary_reason_codes: ['OVERDUE_REVIEW', 'RECENT_ERROR', 'LOW_MASTERY'],
        explanation_summary: '容量 10 件を復習だけで埋めた。期限到来のうち 4 件を繰り越した。',
      }),
    )
    const onStartToday = vi.fn()
    render(<TutorTodayLearningCard onStartToday={onStartToday} />)

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-total-count')).toHaveTextContent('10')
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 7 / 新規 3')
    expect(screen.getByText('あとで復習できる項目が 4件あります')).toBeInTheDocument()
    expect(screen.getAllByText('復習時期を迎えています').length).toBeGreaterThan(0)
    expect(screen.getByText('最近この表現で間違えています')).toBeInTheDocument()
    expect(screen.queryByText('まだ定着が十分ではありません')).not.toBeInTheDocument()
    expect(screen.queryByText('LOW_MASTERY')).not.toBeInTheDocument()
    expect(screen.queryByText(/rank_score/)).not.toBeInTheDocument()

    const start = screen.getByRole('button', { name: '学習を始める' })
    expect(start).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(start)
    expect(onStartToday).toHaveBeenCalledTimes(1)
  })

  it('reason が無い entry では理由を捏造しない', async () => {
    mockPlan.mockResolvedValue(
      todayPlanFixture({
        entries: [
          todayPlanEntryFixture({
            reason_codes: [],
            explanation: '今日の学習候補です',
          }),
        ],
        summary_reason_codes: [],
        explanation_summary: '期限到来の復習はなかった。新規 1 件を入れた。',
      }),
    )
    render(<TutorTodayLearningCard onStartToday={() => {}} />)

    await screen.findByRole('button', { name: '学習を始める' })
    expect(screen.queryByText('関心の高い教材に出てきた表現です')).not.toBeInTheDocument()
    expect(screen.queryByText('HIGH_INTEREST')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('今日の学習の理由')).not.toBeInTheDocument()
  })

  it('苦手パターンの説明は項目名を含めて表示する', async () => {
    mockPlan.mockResolvedValue(
      todayPlanFixture({
        entries: [
          todayPlanEntryFixture({
            canonical_form: 'se lever',
            skill_direction: 'production',
            selected_exercise_type: 'ja_to_fr',
            reason_codes: ['PRODUCTION_PATTERN_WEAKNESS'],
            explanation:
              '最近、同じ種類の項目の自力回答で間違いが続いています。最近、代名動詞の自力回答で間違いが続いています。',
          }),
        ],
        summary_reason_codes: ['PRODUCTION_PATTERN_WEAKNESS'],
      }),
    )
    render(<TutorTodayLearningCard onStartToday={() => {}} />)

    await screen.findByLabelText('今日の学習の一部')
    expect(
      screen.getByText(
        '最近、同じ種類の項目の自力回答で間違いが続いています。最近、代名動詞の自力回答で間違いが続いています。',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('最近、同じ種類の項目の自力回答で間違いが続いています'),
    ).toBeInTheDocument()
  })

  it('preview は上位数項目に留める', async () => {
    mockPlan.mockResolvedValue(
      todayPlanFixture({
        review_count: 7,
        new_count: 3,
      }),
    )
    render(<TutorTodayLearningCard onStartToday={() => {}} />)

    await screen.findByLabelText('今日の学習の一部')
    expect(within(screen.getByLabelText('今日の学習の一部')).getAllByRole('listitem')).toHaveLength(3)
  })

  it('Plan 取得失敗時は再試行できる', async () => {
    mockPlan
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockResolvedValueOnce(
        todayPlanFixture({
          review_count: 1,
          new_count: 0,
        }),
      )
    render(<TutorTodayLearningCard onStartToday={() => {}} />)

    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByRole('button', { name: '学習を始める' })
    expect(screen.getByTestId('today-total-count')).toHaveTextContent('1')
  })

  it('loading 中は件数を確定表示しない', () => {
    mockPlan.mockImplementation(() => new Promise(() => {}))
    render(<TutorTodayLearningCard onStartToday={() => {}} />)
    expect(screen.getByText('読み込み中...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '学習を始める' })).not.toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  ApiError,
  createPracticeSession,
  createReviewSession,
  createTodaySession,
  fetchReviewQueue,
  fetchTodayPlan,
  fetchTutorItem,
  fetchTutorItems,
  fetchTutorSources,
  submitExerciseAnswer,
} from '../api/tutor'
import type {
  ExerciseFeedback,
  ExerciseView,
  LearningItem,
  SourceSummary,
} from '../types'
import { EMPTY_REVIEW_QUEUE, reviewQueueFixture } from './reviewQueueFixtures'
import {
  EMPTY_TODAY_PLAN,
  todayPlanEntryFixture,
  todayPlanFixture,
  todaySessionFixture,
} from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchCandidates: vi.fn(),
    createPracticeSession: vi.fn(),
    createReviewSession: vi.fn(),
    createTodaySession: vi.fn(),
    fetchTutorItems: vi.fn(),
    fetchTutorItem: vi.fn(),
    submitExerciseAnswer: vi.fn(),
    fetchReviewQueue: vi.fn(),
    fetchTodayPlan: vi.fn(),
  }
})

const ttsState = { error: null as string | null, play: vi.fn() }

vi.mock('../hooks/useTTS', () => ({
  useTTS: () => ({
    play: ttsState.play,
    isLoading: false,
    error: ttsState.error,
    clearError: vi.fn(),
  }),
}))

const mockList = vi.mocked(fetchTutorSources)
const mockPractice = vi.mocked(createPracticeSession)
const mockReview = vi.mocked(createReviewSession)
const mockToday = vi.mocked(createTodaySession)
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockSubmit = vi.mocked(submitExerciseAnswer)
const mockQueue = vi.mocked(fetchReviewQueue)
const mockPlan = vi.mocked(fetchTodayPlan)

const SUMMARY: SourceSummary = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  content_preview: "Il s'agit d'un article.",
}

const VOCAB: LearningItem = {
  id: 'item-vocab',
  item_type: 'vocabulary',
  canonical_form: 'livre',
  meaning_ja: '本',
  explanation_ja: '読むもの',
  level: 'A1',
  source_refs: [],
  created_at: '2026-08-24T12:00:00+00:00',
  status: 'active',
}

const EXPR: LearningItem = {
  id: 'item-expr',
  item_type: 'expression',
  canonical_form: 'bonjour',
  meaning_ja: 'こんにちは',
  explanation_ja: 'あいさつ',
  level: 'A1',
  source_refs: [],
  created_at: '2026-08-24T12:00:00+00:00',
  status: 'active',
}

const CHOICE: ExerciseView = {
  learning_item_id: 'item-vocab',
  exercise_type: 'meaning_recognition',
  skill_direction: 'recognition',
  prompt: '次のフランス語の意味を選んでください。\n\nlivre',
  response_kind: 'choice',
  options: ['本', '家', '猫', '犬'],
  source_context: null,
  exercise_version: 'exercise-v1',
}

const TEXT: ExerciseView = {
  learning_item_id: 'item-expr',
  exercise_type: 'ja_to_fr',
  skill_direction: 'production',
  prompt: '次の意味をフランス語で書いてください。\n\nこんにちは',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

function okFeedback(
  correctAnswer: string,
  given: string | string[],
  extra: Partial<ExerciseFeedback> = {},
): ExerciseFeedback {
  return {
    correct: true,
    correct_answer: correctAnswer,
    given,
    explanation_ja: extra.explanation_ja ?? '読むもの',
    source_context: extra.source_context ?? null,
    meaning_ja: extra.meaning_ja ?? null,
    canonical_form: extra.canonical_form ?? null,
  }
}

describe('Tutor Phase 5 today learning flow', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    ttsState.error = null
    ttsState.play = vi.fn()
    mockList.mockResolvedValue([SUMMARY])
    mockItems.mockResolvedValue([VOCAB, EXPR])
    mockItem.mockImplementation(async id => {
      const found = [VOCAB, EXPR].find(row => row.id === id)
      if (!found) throw new ApiError(404)
      return found
    })
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
  })

  it('今日の学習から既存 renderer で完了し、件数を更新する', async () => {
    mockPlan
      .mockResolvedValueOnce(
        todayPlanFixture({
          review_count: 7,
          new_count: 3,
          deferred_due_count: 2,
          summary_reason_codes: ['OVERDUE_REVIEW', 'RECENT_SOURCE'],
        }),
      )
      .mockResolvedValue(todayPlanFixture({ review_count: 2, new_count: 0 }))
    mockQueue
      .mockResolvedValueOnce(reviewQueueFixture({ total_due: 9 }))
      .mockResolvedValue(reviewQueueFixture({ total_due: 2, production_due: 2 }))
    mockToday.mockResolvedValue(
      todaySessionFixture(
        [CHOICE, TEXT],
        [
          todayPlanEntryFixture({
            learning_item_id: 'item-vocab',
            activity_kind: 'review',
            reason_codes: ['OVERDUE_REVIEW'],
          }),
          todayPlanEntryFixture({
            learning_item_id: 'item-expr',
            canonical_form: 'bonjour',
            activity_kind: 'new_practice',
            skill_direction: 'production',
            selected_exercise_type: 'ja_to_fr',
            reason_codes: ['RECENT_SOURCE'],
          }),
        ],
        { deferred_due_count: 2 },
      ),
    )
    mockSubmit
      .mockResolvedValueOnce(okFeedback('本', '本'))
      .mockResolvedValueOnce(okFeedback('bonjour', 'bonjour'))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-total-count')).toHaveTextContent('10')
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 7 / 新規 3')
    expect(screen.getByText('あとで復習できる項目が 2件あります')).toBeInTheDocument()
    expect(screen.getAllByText('復習時期を迎えています').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: '今日の復習' })).toBeInTheDocument()
    const start = screen.getByRole('button', { name: '学習を始める' })
    expect(start).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(start)

    await screen.findByText('意味')
    expect(screen.queryByText('出題数を選択')).not.toBeInTheDocument()
    expect(mockToday).toHaveBeenCalledWith({ question_count: 10 })
    expect(mockPractice).not.toHaveBeenCalled()
    expect(mockReview).not.toHaveBeenCalled()
    expect(screen.getByText('復習')).toBeInTheDocument()
    expect(CHOICE).not.toHaveProperty('correct_answer')

    const choice = screen.getByRole('button', { name: '本' })
    expect(choice).toHaveStyle({ minHeight: '48px', width: '100%' })
    await userEvent.click(choice)
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByPlaceholderText('回答を入力...')
    expect(screen.getByText('新しい項目')).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'bonjour', { delay: null })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByText('今日の学習を終えました')).toBeInTheDocument()
    expect(screen.getByTestId('today-result-mix')).toHaveTextContent('復習 1件 / 新規 1件')
    expect(screen.getByText('正解')).toBeInTheDocument()
    expect(screen.queryByText(/完全習得|習熟|マスター|mastery/i)).not.toBeInTheDocument()
    await screen.findByText('あとで復習できる項目が 2件あります')

    await userEvent.click(screen.getByRole('button', { name: '教材一覧へ戻る' }))
    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 2 / 新規 0')
    expect(screen.getByRole('heading', { name: '今日の復習' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '学習する' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Le Monde/ })).toBeInTheDocument()
  })

  it('empty plan でも Phase 4 の復習導線と通常 Practice が残る', async () => {
    mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
    mockQueue.mockResolvedValue(
      reviewQueueFixture({ total_due: 3, recognition_due: 1, production_due: 2 }),
    )
    mockPractice.mockResolvedValue({
      session_id: 'sess-1',
      exercises: [CHOICE],
      skipped_items: [],
      requested_count: 5,
      generated_count: 1,
    })

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('今日は学習できる項目がありません')
    expect(screen.queryByRole('button', { name: '学習を始める' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '復習を始める' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    await screen.findByText('意味')
    expect(mockPractice).toHaveBeenCalledWith({ source_id: undefined, question_count: 5 })
    expect(mockToday).not.toHaveBeenCalled()
  })

  it('Session開始失敗後に戻っても Plan 表示は残る', async () => {
    mockPlan.mockResolvedValue(todayPlanFixture({ review_count: 2, new_count: 1 }))
    mockToday.mockRejectedValue(new ApiError(500))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByRole('button', { name: '学習を始める' })
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 2 / 新規 1')
    await userEvent.click(screen.getByRole('button', { name: '学習を始める' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('button', { name: '学習を始める' })
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 2 / 新規 1')
  })

  it('stale skip は技術エラーを出さず残りの問題を続ける', async () => {
    mockPlan.mockResolvedValue(todayPlanFixture({ review_count: 1, new_count: 1 }))
    mockToday.mockResolvedValue(
      todaySessionFixture(
        [CHOICE],
        [
          todayPlanEntryFixture({
            learning_item_id: 'item-vocab',
            activity_kind: 'review',
          }),
        ],
        {
          skipped_entries: [
            {
              learning_item_id: 'item-gone',
              skill_direction: 'production',
              activity_kind: 'review',
              skip_reason: 'stale_due',
              detail: 'due ではなくなった',
            },
          ],
        },
      ),
    )
    mockSubmit.mockResolvedValue(okFeedback('本', '本'))
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '学習を始める' }))
    await screen.findByText('意味')
    expect(screen.queryByText('stale_due')).not.toBeInTheDocument()
    expect(screen.queryByText('due ではなくなった')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '本' }))
    await userEvent.click(await screen.findByRole('button', { name: '結果を見る →' }))
    await screen.findByText('今日の学習を終えました')
  })

  it('回答送信失敗時は現在問題を失わない', async () => {
    mockPlan.mockResolvedValue(todayPlanFixture({ review_count: 1 }))
    mockToday.mockResolvedValue(todaySessionFixture([TEXT]))
    mockSubmit.mockRejectedValue(new ApiError(500, { detail: 'boom' }))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '学習を始める' }))
    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'bonjour', { delay: null })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveValue('bonjour')
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.queryByText('今日の学習を終えました')).not.toBeInTheDocument()
  })

  it('推奨fixtureの overdue / production弱点 / 新規が Tutor 上で区別できる', async () => {
    const entries = [
      todayPlanEntryFixture({
        learning_item_id: 'item-expr',
        canonical_form: 'se rendre compte de',
        meaning_ja: '〜に気づく',
        item_type: 'expression',
        activity_kind: 'review',
        skill_direction: 'production',
        selected_exercise_type: 'ja_to_fr',
        reason_codes: ['OVERDUE_REVIEW'],
        explanation: '復習時期を迎えています。',
      }),
      todayPlanEntryFixture({
        learning_item_id: 'item-vocab',
        canonical_form: 'stratégie',
        meaning_ja: '戦略',
        activity_kind: 'review',
        skill_direction: 'production',
        selected_exercise_type: 'ja_to_fr',
        reason_codes: ['PRODUCTION_WEAKER', 'RECENT_ERROR'],
        explanation:
          '意味は分かっていますが、自分で言う練習が不足しています。最近この項目で間違えています。',
      }),
      todayPlanEntryFixture({
        learning_item_id: 'item-new-c',
        canonical_form: 'bonjour',
        meaning_ja: 'こんにちは',
        activity_kind: 'new_practice',
        skill_direction: 'recognition',
        selected_exercise_type: 'meaning_recognition',
        reason_codes: ['RECENT_SOURCE'],
        explanation: '最近追加した教材に出てきた表現です。',
      }),
      todayPlanEntryFixture({
        learning_item_id: 'item-new-d',
        canonical_form: 'ancien',
        meaning_ja: '古い',
        activity_kind: 'new_practice',
        reason_codes: [],
        explanation: '今日の学習候補です。',
      }),
      todayPlanEntryFixture({
        learning_item_id: 'item-new-e',
        canonical_form: 'mystère',
        meaning_ja: '謎',
        activity_kind: 'new_practice',
        reason_codes: [],
        explanation: '今日の学習候補です。',
      }),
    ]
    mockPlan
      .mockResolvedValueOnce(
        todayPlanFixture({
          entries,
          deferred_due_count: 0,
          summary_reason_codes: ['OVERDUE_REVIEW', 'PRODUCTION_WEAKER', 'RECENT_SOURCE'],
        }),
      )
      .mockResolvedValue(
        todayPlanFixture({
          review_count: 1,
          new_count: 2,
        }),
      )
    mockToday.mockResolvedValue(
      todaySessionFixture(
        [TEXT, CHOICE],
        [entries[0], entries[2]],
      ),
    )
    mockSubmit
      .mockResolvedValueOnce(okFeedback('se rendre compte de', 'se rendre compte de'))
      .mockResolvedValueOnce(okFeedback('本', '本'))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-total-count')).toHaveTextContent('5')
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 2 / 新規 3')
    expect(screen.getByText('se rendre compte de')).toBeInTheDocument()
    expect(screen.getByText('stratégie')).toBeInTheDocument()
    expect(screen.getByText('bonjour')).toBeInTheDocument()
    expect(screen.queryByText('LEVEL_FIT')).not.toBeInTheDocument()
    expect(screen.queryByText('HIGH_INTEREST')).not.toBeInTheDocument()
    expect(screen.getAllByText('復習時期を迎えています').length).toBeGreaterThan(0)
    expect(
      screen.getByText('意味は分かっていますが、自分で言う練習を優先します'),
    ).toBeInTheDocument()
    const start = screen.getByRole('button', { name: '学習を始める' })
    expect(start).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(start)

    await screen.findByPlaceholderText('回答を入力...')
    expect(screen.getByText('復習')).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'se rendre compte de', {
      delay: null,
    })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await userEvent.click(await screen.findByRole('button', { name: '次の問題 →' }))

    await screen.findByText('意味')
    expect(screen.getByText('新しい項目')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '本' }))
    await userEvent.click(await screen.findByRole('button', { name: '結果を見る →' }))

    await screen.findByText('今日の学習を終えました')
    expect(screen.getByTestId('today-result-mix')).toHaveTextContent('復習 1件 / 新規 1件')
    await userEvent.click(screen.getByRole('button', { name: '教材一覧へ戻る' }))
    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 1 / 新規 2')
    expect(screen.getByRole('heading', { name: '今日の復習' })).toBeInTheDocument()
  })

  it('完了後の plan/due 再取得失敗でも学習結果は残る', async () => {
    mockPlan
      .mockResolvedValueOnce(todayPlanFixture({ review_count: 1 }))
      .mockRejectedValue(new ApiError(500))
    mockToday.mockResolvedValue(todaySessionFixture([CHOICE]))
    mockQueue.mockRejectedValue(new ApiError(500))
    mockSubmit.mockResolvedValue(okFeedback('本', '本'))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '学習を始める' }))
    await userEvent.click(await screen.findByRole('button', { name: '本' }))
    await userEvent.click(await screen.findByRole('button', { name: '結果を見る →' }))
    await screen.findByText('今日の学習を終えました')
    expect(screen.getByText('正解')).toBeInTheDocument()
    expect(screen.queryByText(/あとで復習できる項目/)).not.toBeInTheDocument()
  })
})

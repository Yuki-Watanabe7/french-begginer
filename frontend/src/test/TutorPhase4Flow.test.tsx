import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  ApiError,
  createPracticeSession,
  createReviewSession,
  fetchReviewQueue,
  fetchTutorItem,
  fetchTutorItems,
  fetchTutorSources,
  submitExerciseAnswer,
} from '../api/tutor'
import type {
  ExerciseFeedback,
  ExerciseView,
  LearningItem,
  ReviewPracticeSession,
  SourceSummary,
} from '../types'
import { EMPTY_REVIEW_QUEUE, reviewQueueFixture } from './reviewQueueFixtures'

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
    fetchTutorItems: vi.fn(),
    fetchTutorItem: vi.fn(),
    submitExerciseAnswer: vi.fn(),
    fetchReviewQueue: vi.fn(),
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
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockSubmit = vi.mocked(submitExerciseAnswer)
const mockQueue = vi.mocked(fetchReviewQueue)

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
  canonical_form: 'se rendre compte de',
  meaning_ja: '〜に気づく',
  explanation_ja: 'よく使う',
  level: 'A2',
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
  learning_item_id: 'item-vocab',
  exercise_type: 'ja_to_fr',
  skill_direction: 'production',
  prompt: '次の意味をフランス語で書いてください。\n\n本',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

const CLOZE: ExerciseView = {
  learning_item_id: 'item-expr',
  exercise_type: 'cloze',
  skill_direction: 'production',
  prompt: '次の空欄に入るフランス語を、原文のまま書いてください。\n\nJe me suis ____.',
  response_kind: 'text',
  options: null,
  source_context: 'Je me suis ____.',
  exercise_version: 'exercise-v1',
}

const RECON: ExerciseView = {
  learning_item_id: 'item-expr',
  exercise_type: 'expression_reconstruction',
  skill_direction: 'production',
  prompt: '次の語を正しい順に並べて、表現を完成させてください。',
  response_kind: 'reconstruction',
  options: ['compte', 'se', 'de', 'rendre'],
  source_context: null,
  exercise_version: 'exercise-v1',
}

const VERB_EX: ExerciseView = {
  learning_item_id: 'item-verb',
  exercise_type: 'verb_conjugation',
  skill_direction: 'production',
  prompt:
    '次の動詞を、指定された時制・主語で活用してください。\n\n動詞: parler\n時制: présent\n主語: je',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

function reviewSession(exercises: ExerciseView[]): ReviewPracticeSession {
  return {
    session_id: 'rev-1',
    exercises,
    skipped_entries: [],
    requested_count: exercises.length || 5,
    generated_count: exercises.length,
  }
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

describe('Tutor Phase 4 review flow', () => {
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
  })

  it('due件数から復習を開始し、renderer を再利用して完了後に件数を更新する', async () => {
    mockQueue
      .mockResolvedValueOnce(
        reviewQueueFixture({
          total_due: 7,
          recognition_due: 4,
          production_due: 3,
          overdue_count: 2,
        }),
      )
      .mockResolvedValueOnce(reviewQueueFixture({ total_due: 2, production_due: 2 }))
      .mockResolvedValueOnce(reviewQueueFixture({ total_due: 2, production_due: 2 }))
    mockReview.mockResolvedValue(reviewSession([CHOICE, TEXT, CLOZE, RECON, VERB_EX]))
    mockSubmit
      .mockResolvedValueOnce(okFeedback('本', '本'))
      .mockResolvedValueOnce(okFeedback('livre', 'livre'))
      .mockResolvedValueOnce(
        okFeedback('rendu compte', 'rendu compte', { source_context: 'Je me suis ____.' }),
      )
      .mockResolvedValueOnce(okFeedback('se rendre compte de', ['se', 'rendre', 'compte', 'de']))
      .mockResolvedValueOnce(okFeedback('parle', 'parle', { explanation_ja: null }))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))

    await screen.findByRole('heading', { name: '今日の復習' })
    expect(screen.getByTestId('due-count')).toHaveTextContent('7')
    expect(screen.getByText('期限を過ぎた復習 2件')).toBeInTheDocument()
    expect(screen.getByText('見て分かる練習 4件 / 自分で言う練習 3件')).toBeInTheDocument()
    const startReview = screen.getByRole('button', { name: '復習を始める' })
    expect(startReview).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(startReview)
    await screen.findByText('出題数を選択')
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))

    await screen.findByText('意味')
    expect(mockReview).toHaveBeenCalledWith({ question_count: 5 })
    expect(mockPractice).not.toHaveBeenCalled()
    expect(CHOICE).not.toHaveProperty('correct_answer')
    const choice = screen.getByRole('button', { name: '本' })
    expect(choice).toHaveStyle({ minHeight: '48px', width: '100%' })
    await userEvent.click(choice)
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'livre', { delay: null })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('穴埋め')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'rendu compte', {
      delay: null,
    })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('Je me suis ____.')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('並べ替え')
    await userEvent.click(screen.getByRole('button', { name: 'se' }))
    await userEvent.click(screen.getByRole('button', { name: 'rendre' }))
    await userEvent.click(screen.getByRole('button', { name: 'compte' }))
    await userEvent.click(screen.getByRole('button', { name: 'de' }))
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('活用')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'parle', { delay: null })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))

    await screen.findByText('復習完了')
    expect(screen.getByText('今日の復習を終えました')).toBeInTheDocument()
    expect(screen.getByText('正解')).toBeInTheDocument()
    expect(screen.queryByText(/習熟|マスター|mastery/i)).not.toBeInTheDocument()
    await screen.findByText('まだ残っている復習は 2件です')

    await userEvent.click(screen.getByRole('button', { name: '教材一覧へ戻る' }))
    await screen.findByRole('heading', { name: '今日の復習' })
    expect(screen.getByTestId('due-count')).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: '学習する' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Le Monde/ })).toBeInTheDocument()
  })

  it('due 0件なら empty state を出し、通常Practiceへ戻れる', async () => {
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockPractice.mockResolvedValue({
      session_id: 'sess-1',
      exercises: [CHOICE],
      skipped_items: [],
      requested_count: 5,
      generated_count: 1,
    })

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('今すぐ復習する項目はありません')
    expect(screen.queryByRole('button', { name: '復習を始める' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    await screen.findByText('意味')
    expect(mockPractice).toHaveBeenCalledWith({ source_id: undefined, question_count: 5 })
    expect(mockReview).not.toHaveBeenCalled()
  })

  it('Session開始失敗後に戻っても due件数は残る', async () => {
    mockQueue.mockResolvedValue(
      reviewQueueFixture({ total_due: 3, recognition_due: 1, production_due: 2 }),
    )
    mockReview.mockRejectedValue(new ApiError(500))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByRole('button', { name: '復習を始める' })
    expect(screen.getByTestId('due-count')).toHaveTextContent('3')
    await userEvent.click(screen.getByRole('button', { name: '復習を始める' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('button', { name: '復習を始める' })
    expect(screen.getByTestId('due-count')).toHaveTextContent('3')
  })

  it('不正解でも現在問題を保持し、結果に不正解数を載せる', async () => {
    mockQueue
      .mockResolvedValueOnce(reviewQueueFixture({ total_due: 1, recognition_due: 1 }))
      .mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockReview.mockResolvedValue(reviewSession([CHOICE]))
    mockSubmit.mockResolvedValue({
      correct: false,
      correct_answer: '本',
      given: '家',
      explanation_ja: '読むもの',
      source_context: null,
      meaning_ja: null,
      canonical_form: null,
    })

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '復習を始める' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    await userEvent.click(await screen.findByRole('button', { name: '家' }))
    await screen.findByText('✗ 不正解')
    expect(screen.getByText(/正解:/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))
    await screen.findByText('復習完了')
    expect(screen.getByText('不正解')).toBeInTheDocument()
  })

  it('TTS失敗でも Review Session を続けられ、判定ボタンは隠れすぎない', async () => {
    mockQueue
      .mockResolvedValueOnce(reviewQueueFixture({ total_due: 1, recognition_due: 1 }))
      .mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockReview.mockResolvedValue(reviewSession([CHOICE]))
    mockSubmit.mockResolvedValue(okFeedback('本', '本'))
    ttsState.error = '音声を読み込めませんでした'

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '復習を始める' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    const choice = await screen.findByRole('button', { name: '本' })
    expect(choice).toHaveStyle({ minHeight: '48px', width: '100%' })
    await userEvent.click(choice)
    await screen.findByText('✓ 正解')
    expect(screen.getByText('音声を読み込めませんでした')).toBeInTheDocument()
    const next = screen.getByRole('button', { name: '結果を見る →' })
    expect(next).toHaveStyle({ minHeight: '48px', width: '100%' })
    await userEvent.click(next)
    await screen.findByText('復習完了')
    expect(screen.getByRole('button', { name: '教材一覧へ戻る' })).toHaveStyle({
      minHeight: '44px',
      width: '100%',
    })
  })

  it('回答送信失敗時は現在問題を失わない', async () => {
    mockQueue.mockResolvedValue(reviewQueueFixture({ total_due: 1, production_due: 1 }))
    mockReview.mockResolvedValue(reviewSession([TEXT]))
    mockSubmit.mockRejectedValue(new ApiError(500, { detail: 'boom' }))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await userEvent.click(await screen.findByRole('button', { name: '復習を始める' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))
    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'livre', { delay: null })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveValue('livre')
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.queryByText('復習完了')).not.toBeInTheDocument()
  })
})

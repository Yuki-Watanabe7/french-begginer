import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  clearItemKnown,
  createTodaySession,
  fetchCandidates,
  fetchReviewQueue,
  fetchSourceLearningSummary,
  fetchTodayPlan,
  fetchTutorItem,
  fetchTutorItems,
  fetchTutorSource,
  fetchTutorSources,
  markItemKnown,
  submitExerciseAnswer,
} from '../api/tutor'
import type { ExerciseView, LearningItem, LearningItemCandidate, SourceDocument, SourceSummary } from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'
import { sourceLearningSummaryFixture } from './sourceLearningSummaryFixtures'
import { todayPlanEntryFixture, todayPlanFixture, todaySessionFixture } from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    fetchSourceLearningSummary: vi.fn(),
    fetchCandidates: vi.fn(),
    fetchTutorItems: vi.fn(),
    fetchTutorItem: vi.fn(),
    fetchReviewQueue: vi.fn(),
    fetchTodayPlan: vi.fn(),
    createTodaySession: vi.fn(),
    submitExerciseAnswer: vi.fn(),
    markItemKnown: vi.fn(),
    clearItemKnown: vi.fn(),
  }
})

vi.mock('../hooks/useTTS', () => ({
  useTTS: () => ({
    play: vi.fn(),
    isLoading: false,
    error: null,
    clearError: vi.fn(),
  }),
}))

const mockSources = vi.mocked(fetchTutorSources)
const mockSource = vi.mocked(fetchTutorSource)
const mockSummary = vi.mocked(fetchSourceLearningSummary)
const mockCandidates = vi.mocked(fetchCandidates)
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockQueue = vi.mocked(fetchReviewQueue)
const mockPlan = vi.mocked(fetchTodayPlan)
const mockToday = vi.mocked(createTodaySession)
const mockSubmit = vi.mocked(submitExerciseAnswer)
const mockMarkKnown = vi.mocked(markItemKnown)
const mockClearKnown = vi.mocked(clearItemKnown)

const SUMMARY: SourceSummary = {
  id: 'src-pdf',
  source_type: 'pdf',
  title: 'PDFの本',
  language: 'fr',
  created_at: '2026-09-11T12:00:00+00:00',
  content_preview: 'Je lis un livre rouge.',
}

const SOURCE: SourceDocument = {
  id: 'src-pdf',
  source_type: 'pdf',
  title: 'PDFの本',
  content: 'Je lis un livre rouge dans la bibliotheque.',
  language: 'fr',
  created_at: '2026-09-11T12:00:00+00:00',
  metadata: {},
  segments: [
    {
      normalized_start: 0,
      normalized_end: 42,
      page_number: 1,
    },
  ],
}

const LIVRE: LearningItem = {
  id: 'item-livre',
  item_type: 'vocabulary',
  canonical_form: 'livre',
  meaning_ja: '本',
  explanation_ja: null,
  level: null,
  source_refs: [],
  created_at: '2026-10-01T12:00:00+00:00',
  status: 'active',
}

const BONJOUR: LearningItem = {
  id: 'item-bonjour',
  item_type: 'vocabulary',
  canonical_form: 'bonjour',
  meaning_ja: 'こんにちは',
  explanation_ja: null,
  level: null,
  source_refs: [],
  created_at: '2026-10-01T12:00:00+00:00',
  status: 'active',
}

const CANDIDATE: LearningItemCandidate = {
  id: 'cand-bonjour',
  source_document_id: 'src-pdf',
  item_type: 'vocabulary',
  canonical_form: 'bonjour',
  meaning_ja: 'こんにちは',
  explanation_ja: null,
  level: null,
  evidence_span: { start: 0, end: 7 },
  evidence_text: 'bonjour',
  confidence: 0.9,
  status: 'accepted',
  extraction_version: 'extract-v2',
  created_at: '2026-10-01T12:00:00+00:00',
  learning_item_id: 'item-bonjour',
  explicit_known: true,
}

const CLOZE: ExerciseView = {
  learning_item_id: 'item-livre',
  exercise_type: 'cloze',
  skill_direction: 'production',
  prompt: '次の空欄に入るフランス語を、原文のまま書いてください。\n\nJe lis un ____ rouge.',
  response_kind: 'text',
  options: null,
  source_context: 'Je lis un ____ rouge.',
  exercise_version: 'exercise-v1',
}

const NEW_TEXT: ExerciseView = {
  learning_item_id: 'item-bonjour',
  exercise_type: 'ja_to_fr',
  skill_direction: 'production',
  prompt: '次の意味をフランス語で書いてください。\n\nこんにちは',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

describe('Tutor Phase 7 learning quality flow', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockSources.mockResolvedValue([SUMMARY])
    mockSource.mockResolvedValue(SOURCE)
    mockSummary.mockResolvedValue(
      sourceLearningSummaryFixture({
        source_id: 'src-pdf',
        accepted_item_count: 1,
        accepted_candidate_count: 1,
        started_item_count: 1,
        due_direction_count: 1,
        mastered_or_known_count: 1,
        unseen_item_count: 0,
        attempts: 2,
        correct_count: 1,
        correct_rate: 0.5,
        recognition: {
          skill_direction: 'recognition',
          attempt_count: 0,
          correct_count: 0,
          correct_rate: null,
          due_count: 0,
        },
        production: {
          skill_direction: 'production',
          attempt_count: 2,
          correct_count: 1,
          correct_rate: 0.5,
          due_count: 1,
        },
      }),
    )
    mockCandidates.mockResolvedValue([CANDIDATE])
    mockItems.mockResolvedValue([LIVRE, BONJOUR])
    mockItem.mockImplementation(async id => {
      const found = [LIVRE, BONJOUR].find(row => row.id === id)
      if (!found) throw new Error(`missing ${id}`)
      return found
    })
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockMarkKnown.mockResolvedValue({
      learning_item_id: 'item-bonjour',
      explicit_known: true,
      updated_at: '2026-10-02T12:00:00+00:00',
      policy_version: 'known-item-v1',
    })
    mockClearKnown.mockResolvedValue({
      learning_item_id: 'item-bonjour',
      explicit_known: false,
      updated_at: '2026-10-02T12:00:00+00:00',
      policy_version: 'known-item-v1',
    })
  })

  it('今日の学習、別文脈、既知の取り消し、Sourceの学習状況を一連で確認する', async () => {
    const user = userEvent.setup()
    mockPlan.mockResolvedValue(
      todayPlanFixture({
        review_count: 2,
        new_count: 1,
        requested_count: 10,
        explanation_summary:
          '復習 2 件を優先した。新規 1 件を入れた。復習が溜まっている、新しい項目を入れられる枠が狭いため、新しい項目を減らしました。',
        entries: [
          todayPlanEntryFixture({
            learning_item_id: 'item-livre',
            canonical_form: 'livre',
            meaning_ja: '本',
            activity_kind: 'review',
            skill_direction: 'production',
            selected_exercise_type: 'cloze',
            reason_codes: ['OVERDUE_REVIEW', 'PRODUCTION_PATTERN_WEAKNESS'],
            explanation: '復習時期を迎えています。最近、文法の自力回答で間違いが続いています。',
            source_titles: ['PDFの本'],
          }),
          todayPlanEntryFixture({
            learning_item_id: 'item-merci',
            canonical_form: 'merci',
            meaning_ja: 'ありがとう',
            activity_kind: 'review',
            skill_direction: 'production',
            selected_exercise_type: 'ja_to_fr',
            reason_codes: ['OVERDUE_REVIEW'],
            explanation: '復習時期を迎えています。',
            source_titles: ['礼のメモ'],
          }),
          todayPlanEntryFixture({
            learning_item_id: 'item-bonjour',
            canonical_form: 'bonjour',
            meaning_ja: 'こんにちは',
            activity_kind: 'new_practice',
            skill_direction: 'production',
            selected_exercise_type: 'ja_to_fr',
            reason_codes: ['RECENT_SOURCE'],
            explanation: '最近追加した教材に出てきた表現です。',
            source_titles: ['あいさつのメモ'],
          }),
        ],
      }),
    )
    mockToday.mockResolvedValue(
      todaySessionFixture(
        [CLOZE, NEW_TEXT],
        [
          todayPlanEntryFixture({
            learning_item_id: 'item-livre',
            canonical_form: 'livre',
            activity_kind: 'review',
            skill_direction: 'production',
            selected_exercise_type: 'cloze',
            reason_codes: ['OVERDUE_REVIEW'],
            source_titles: ['PDFの本'],
          }),
          todayPlanEntryFixture({
            learning_item_id: 'item-bonjour',
            canonical_form: 'bonjour',
            meaning_ja: 'こんにちは',
            activity_kind: 'new_practice',
            skill_direction: 'production',
            selected_exercise_type: 'ja_to_fr',
            reason_codes: ['RECENT_SOURCE'],
            source_titles: ['あいさつのメモ'],
          }),
        ],
      ),
    )
    mockSubmit
      .mockResolvedValueOnce({
        correct: true,
        correct_answer: 'livre',
        given: 'livre',
        explanation_ja: null,
        source_context: 'Je lis un ____ rouge.',
        meaning_ja: '本',
        canonical_form: 'livre',
      })
      .mockResolvedValueOnce({
        correct: true,
        correct_answer: 'bonjour',
        given: 'bonjour',
        explanation_ja: null,
        source_context: null,
        meaning_ja: 'こんにちは',
        canonical_form: 'bonjour',
      })

    render(<App />)
    await user.click(screen.getByText('自分の教材'))

    await screen.findByRole('heading', { name: '今日の学習' })
    expect(screen.getByTestId('today-mix')).toHaveTextContent('復習 2 / 新規 1')
    expect(
      screen.getByText(
        /復習が溜まっている、新しい項目を入れられる枠が狭いため、新しい項目を減らしました/,
      ),
    ).toBeInTheDocument()
    const start = screen.getByRole('button', { name: '学習を始める' })
    expect(start).toHaveStyle({ width: '100%', minHeight: '48px' })
    const sourceButton = screen.getByRole('button', { name: /PDFの本/ })
    expect(sourceButton).toHaveStyle({ width: '100%' })
    expect(screen.getByText('PDFの本')).toHaveStyle({ overflowWrap: 'anywhere' })

    await user.click(start)
    expect(await screen.findByText(/Je lis un ____ rouge/)).toBeInTheDocument()
    expect(screen.queryByText('出題数を選択')).not.toBeInTheDocument()
    expect(mockToday).toHaveBeenCalledWith({})
    const input = screen.getByPlaceholderText('回答を入力...')
    await user.type(input, 'livre')
    await user.click(screen.getByRole('button', { name: '判定する' }))
    const context = await screen.findByText('Je lis un ____ rouge.')
    expect(context.tagName).toBe('BLOCKQUOTE')

    await user.click(screen.getByRole('button', { name: '次の問題 →' }))
    await screen.findByRole('button', { name: 'これは知っている' })
    await user.click(screen.getByRole('button', { name: 'これは知っている' }))
    await user.click(screen.getByRole('button', { name: '外す' }))
    expect(await screen.findByText('知っているので、新しい学習には出しません')).toBeInTheDocument()
    expect(mockMarkKnown).toHaveBeenCalledWith('item-bonjour')
    await user.click(screen.getByRole('button', { name: '元に戻す' }))
    expect(mockClearKnown).toHaveBeenCalledWith('item-bonjour')
    expect(await screen.findByRole('button', { name: 'これは知っている' })).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('回答を入力...'), 'bonjour')
    await user.click(screen.getByRole('button', { name: '判定する' }))
    await user.click(await screen.findByRole('button', { name: '結果を見る →' }))
    await screen.findByText('今日の学習を終えました')
    await user.click(screen.getByRole('button', { name: '教材一覧へ戻る' }))

    await user.click(await screen.findByRole('button', { name: /PDFの本/ }))
    expect(await screen.findByRole('heading', { name: '学習状況' })).toBeInTheDocument()
    expect(screen.getByTestId('source-learning-accepted')).toHaveTextContent('採用した項目 1')
    expect(screen.getByTestId('source-learning-started')).toHaveTextContent('学習開始済み 1')
    expect(screen.getByTestId('source-learning-due')).toHaveTextContent('復習待ち 1')
    expect(screen.getByTestId('source-learning-known')).toHaveTextContent('既知/十分定着 1')
    expect(screen.getByText('見て分かる 未学習')).toBeInTheDocument()
    expect(screen.getByText('自分で言う 1/2')).toBeInTheDocument()
    expect(screen.getByTestId('source-learning-known')).toHaveStyle({ overflowWrap: 'anywhere' })
    expect(await screen.findByText('知っているので、新しい学習には出しません')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '元に戻す' })).toHaveStyle({ minHeight: '44px' })
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import {
  ApiError,
  acceptCandidate,
  createPracticeSession,
  createTutorSource,
  extractCandidates,
  fetchCandidates,
  fetchSourceLearningSummary,
  fetchTutorItem,
  fetchTutorItems,
  fetchTutorSource,
  fetchTutorSources,
  rejectCandidate,
  submitExerciseAnswer,
  fetchReviewQueue,
  fetchTodayPlan,
} from '../api/tutor'
import type {
  AcceptCandidateResponse,
  CreateTutorSourceInput,
  ExerciseFeedback,
  ExerciseView,
  ExtractCandidatesResponse,
  LearningItem,
  LearningItemCandidate,
  LearningItemType,
  PracticeSession,
  SourceDocument,
  SourceSummary,
} from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'
import { EMPTY_SOURCE_LEARNING_SUMMARY } from './sourceLearningSummaryFixtures'
import { EMPTY_TODAY_PLAN } from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchCandidates: vi.fn(),
    fetchSourceLearningSummary: vi.fn(),
    extractCandidates: vi.fn(),
    acceptCandidate: vi.fn(),
    rejectCandidate: vi.fn(),
    createPracticeSession: vi.fn(),
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
const mockGet = vi.mocked(fetchTutorSource)
const mockCreate = vi.mocked(createTutorSource)
const mockFetchCandidates = vi.mocked(fetchCandidates)
const mockSummary = vi.mocked(fetchSourceLearningSummary)
const mockExtract = vi.mocked(extractCandidates)
const mockAccept = vi.mocked(acceptCandidate)
const mockReject = vi.mocked(rejectCandidate)
const mockPractice = vi.mocked(createPracticeSession)
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockSubmit = vi.mocked(submitExerciseAnswer)
const mockQueue = vi.mocked(fetchReviewQueue)
const mockPlan = vi.mocked(fetchTodayPlan)

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
      item_type: 'vocabulary',
      canonical_form: 'stratégie',
      meaning_ja: '戦略',
      evidence_text: 'stratégie',
      explanation_ja: null,
    },
    {
      item_type: 'grammar',
      canonical_form: 'il fallait',
      meaning_ja: '〜しなければならなかった',
      evidence_text: 'il fallait',
      explanation_ja: '義務の過去',
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

const EXPR: LearningItem = {
  id: 'item-expr',
  item_type: 'expression',
  canonical_form: 'se rendre compte de',
  meaning_ja: '〜に気づく',
  explanation_ja: 'よく出る表現',
  level: 'A2',
  source_refs: [],
  created_at: '2026-08-24T12:30:00.000Z',
  status: 'active',
}

const VOCAB: LearningItem = {
  id: 'item-vocab',
  item_type: 'vocabulary',
  canonical_form: 'stratégie',
  meaning_ja: '戦略',
  explanation_ja: null,
  level: 'A2',
  source_refs: [],
  created_at: '2026-08-24T12:30:00.000Z',
  status: 'active',
}

const VERB: LearningItem = {
  id: 'item-verb',
  item_type: 'conjugation',
  canonical_form: 'parler',
  meaning_ja: '話す',
  explanation_ja: null,
  level: 'A1',
  source_refs: [],
  created_at: '2026-08-24T12:30:00.000Z',
  status: 'active',
}

const CHOICE: ExerciseView = {
  learning_item_id: 'item-vocab',
  exercise_type: 'meaning_recognition',
  skill_direction: 'recognition',
  prompt: '次のフランス語の意味を選んでください。\n\nstratégie',
  response_kind: 'choice',
  options: ['戦略', '〜に気づく', '変える', '話す'],
  source_context: null,
  exercise_version: 'exercise-v1',
}

const TEXT: ExerciseView = {
  learning_item_id: 'item-expr',
  exercise_type: 'ja_to_fr',
  skill_direction: 'production',
  prompt: '次の意味をフランス語で書いてください。\n\n〜に気づく',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

const CLOZE: ExerciseView = {
  learning_item_id: 'item-expr',
  exercise_type: 'cloze',
  skill_direction: 'production',
  prompt:
    "次の空欄に入るフランス語を、原文のまま書いてください。\n\nJe me suis ____ qu'il fallait changer de stratégie.",
  response_kind: 'text',
  options: null,
  source_context: "Je me suis ____ qu'il fallait changer de stratégie.",
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

function session(exercises: ExerciseView[]): PracticeSession {
  return {
    session_id: 'sess-phase3',
    exercises,
    skipped_items: [],
    requested_count: exercises.length,
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
    explanation_ja: extra.explanation_ja ?? 'よく出る表現',
    source_context: extra.source_context ?? null,
    meaning_ja: extra.meaning_ja ?? null,
    canonical_form: extra.canonical_form ?? null,
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
  mockItems.mockImplementation(async () => [...store.items.values(), VOCAB, EXPR, VERB])
  mockItem.mockImplementation(async id => {
    const found = [...store.items.values(), VOCAB, EXPR, VERB].find(row => row.id === id)
    if (!found) throw new ApiError(404)
    return found
  })
  mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
  mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
}

async function saveFixtureSource() {
  await userEvent.click(screen.getByRole('button', { name: '教材を追加' }))
  await userEvent.type(screen.getByLabelText(/タイトル/), SOURCE_TITLE, { delay: null })
  await userEvent.type(screen.getByLabelText(/本文/), SOURCE_CONTENT, { delay: null })
  await userEvent.type(screen.getByLabelText(/メモ/), SOURCE_NOTE, { delay: null })
  await userEvent.click(screen.getByRole('button', { name: '保存する' }))
  await screen.findByRole('heading', { name: SOURCE_TITLE })
}

describe('Tutor Phase 3 vertical slice', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    ttsState.error = null
    ttsState.play = vi.fn()
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
    mockSummary.mockResolvedValue(EMPTY_SOURCE_LEARNING_SUMMARY)
  })

  it('採用した LearningItem から練習し、全形式を解いて結果まで一本でつながる', async () => {
    const store = createStore()
    bindMemoryApi(store)
    mockPractice.mockResolvedValue(session([CHOICE, TEXT, CLOZE, RECON, VERB_EX]))
    mockSubmit
      .mockResolvedValueOnce(okFeedback('戦略', '戦略', { explanation_ja: null }))
      .mockResolvedValueOnce(okFeedback('se rendre compte de', 'se rendre compte de'))
      .mockResolvedValueOnce(
        okFeedback('rendu compte', 'rendu compte', {
          source_context: "Je me suis ____ qu'il fallait changer de stratégie.",
        }),
      )
      .mockResolvedValueOnce(
        okFeedback('se rendre compte de', ['se', 'rendre', 'compte', 'de']),
      )
      .mockResolvedValueOnce(okFeedback('parle', 'parle', { explanation_ja: null }))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()

    await userEvent.click(screen.getByRole('button', { name: '学習候補を抽出' }))
    await screen.findByText('4件の新しい候補を抽出しました')
    const expressionCard = screen.getByRole('article', {
      name: '表現 se rendre compte de',
    })
    await userEvent.click(within(expressionCard).getByRole('button', { name: '採用する' }))
    await within(expressionCard).findByText('採用済み')

    const startPractice = screen.getByRole('button', { name: '学習する' })
    expect(startPractice).toHaveStyle({ width: '100%', minHeight: '48px' })
    await userEvent.click(startPractice)
    await screen.findByText('出題数を選択')
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))

    await screen.findByText('意味')
    expect(mockPractice).toHaveBeenCalledWith({ source_id: 'src-1', question_count: 5 })
    expect(CHOICE).not.toHaveProperty('correct_answer')
    const choice = screen.getByRole('button', { name: '戦略' })
    expect(choice).toHaveStyle({ minHeight: '48px', width: '100%' })
    const prompt = document.querySelector('p[lang="fr"]')
    expect(prompt).toHaveTextContent('stratégie')
    expect(prompt).toHaveStyle({ overflowWrap: 'anywhere' })
    await userEvent.click(choice)
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByPlaceholderText('回答を入力...')
    const textInput = screen.getByPlaceholderText('回答を入力...')
    expect(textInput).toHaveStyle({ width: '100%', fontSize: '20px' })
    await userEvent.type(textInput, 'se rendre compte de', { delay: null })
    const submit = screen.getByRole('button', { name: '判定する' })
    expect(submit).toHaveStyle({ minHeight: '48px', width: '100%' })
    await userEvent.click(submit)
    await screen.findByText('✓ 正解')
    expect(screen.getByText('よく出る表現')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('穴埋め')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'rendu compte', {
      delay: null,
    })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    const evidence = document.querySelector('blockquote[lang="fr"]')
    expect(evidence).toHaveTextContent(
      "Je me suis ____ qu'il fallait changer de stratégie.",
    )
    expect(evidence).toHaveStyle({ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' })
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('並べ替え')
    const token = screen.getByRole('button', { name: 'se' })
    expect(token).toHaveStyle({ minHeight: '44px' })
    await userEvent.click(token)
    await userEvent.click(screen.getByRole('button', { name: 'rendre' }))
    await userEvent.click(screen.getByRole('button', { name: 'compte' }))
    await userEvent.click(screen.getByRole('button', { name: 'de' }))
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('活用')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'parle', {
      delay: null,
    })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    const resultBtn = screen.getByRole('button', { name: '結果を見る →' })
    expect(resultBtn).toHaveStyle({ minHeight: '48px' })
    await userEvent.click(resultBtn)

    await screen.findByText('セッション結果')
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('正解')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('heading', { name: SOURCE_TITLE })

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
    expect(screen.getByText('練習モードを選択')).toBeInTheDocument()
    expect(screen.getByText('動詞活用練習')).toBeInTheDocument()
    expect(screen.getByText('名詞の性クイズ')).toBeInTheDocument()
    expect(screen.getByText('冠詞付き名詞')).toBeInTheDocument()
    expect(screen.getByText('自分の教材')).toBeInTheDocument()
  })

  it('回答送信失敗時は現在問題を失わず、TTS失敗でも学習を続けられる', async () => {
    const store = createStore()
    bindMemoryApi(store)
    ttsState.error = '音声を読み込めませんでした'
    mockPractice.mockResolvedValue(session([TEXT, CHOICE]))
    mockSubmit
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockResolvedValueOnce(okFeedback('se rendre compte de', 'se rendre compte de'))
      .mockResolvedValueOnce(okFeedback('戦略', '戦略', { explanation_ja: null }))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))

    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'se rendre compte de', {
      delay: null,
    })
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveValue('se rendre compte de')
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
    expect(screen.queryByText('セッション結果')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    expect(screen.getByText('音声を読み込めませんでした')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
    await screen.findByText('意味')
    await userEvent.click(screen.getByRole('button', { name: '戦略' }))
    await screen.findByText('✓ 正解')
  })

  it('候補未採用のまま学習すると練習できる項目がないと案内する', async () => {
    bindMemoryApi(createStore())
    mockPractice.mockResolvedValue(session([]))

    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await saveFixtureSource()
    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    await userEvent.click(screen.getByRole('button', { name: /5問/ }))

    await screen.findByText(
      '練習できる学習項目がありません。候補を採用してから学習してください',
    )
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    await screen.findByRole('heading', { name: SOURCE_TITLE })
  })
})

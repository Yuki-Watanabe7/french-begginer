import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PracticeSessionFlow } from '../components/PracticeSessionFlow'
import {
  ApiError,
  createPracticeSession,
  fetchTutorItem,
  fetchTutorItems,
  submitExerciseAnswer,
} from '../api/tutor'
import type { ExerciseView, LearningItem, PracticeSession } from '../types'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    createPracticeSession: vi.fn(),
    fetchTutorItems: vi.fn(),
    fetchTutorItem: vi.fn(),
    submitExerciseAnswer: vi.fn(),
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

const mockCreate = vi.mocked(createPracticeSession)
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockSubmit = vi.mocked(submitExerciseAnswer)

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

const VERB: LearningItem = {
  id: 'item-verb',
  item_type: 'conjugation',
  canonical_form: 'parler',
  meaning_ja: '話す',
  explanation_ja: null,
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
  prompt: '次の動詞を、指定された時制・主語で活用してください。\n\n動詞: parler\n時制: présent\n主語: je',
  response_kind: 'text',
  options: null,
  source_context: null,
  exercise_version: 'exercise-v1',
}

function session(exercises: ExerciseView[]): PracticeSession {
  return {
    session_id: 'sess-1',
    exercises,
    skipped_items: [],
    requested_count: exercises.length,
    generated_count: exercises.length,
  }
}

function okFeedback(
  correctAnswer: string,
  given: string | string[],
  extra: Partial<ReturnType<typeof submitExerciseAnswer> extends Promise<infer T> ? T : never> = {},
) {
  return {
    correct: given === correctAnswer || (Array.isArray(given) && given.join(' ') === correctAnswer),
    correct_answer: correctAnswer,
    given,
    explanation_ja: '読むもの',
    source_context: null as string | null,
    meaning_ja: null,
    canonical_form: null,
    ...extra,
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  mockItems.mockResolvedValue([VOCAB, EXPR, VERB])
  mockItem.mockImplementation(async id => {
    const found = [VOCAB, EXPR, VERB].find(row => row.id === id)
    if (!found) throw new ApiError(404)
    return found
  })
})

describe('PracticeSessionFlow', () => {
  it('Session を開始し choice を正解できる', async () => {
    mockCreate.mockResolvedValue(session([CHOICE]))
    mockSubmit.mockResolvedValue(
      okFeedback('本', '本', { explanation_ja: '読むもの', source_context: null }),
    )
    render(<PracticeSessionFlow questionCount={5} onExit={() => {}} />)

    await screen.findByText('意味')
    expect(mockCreate).toHaveBeenCalledWith({ source_id: undefined, question_count: 5 })
    expect(CHOICE).not.toHaveProperty('correct_answer')
    await userEvent.click(screen.getByRole('button', { name: '本' }))
    await screen.findByText('✓ 正解')
    expect(screen.getByText('読むもの')).toBeInTheDocument()
    expect(screen.getByText('livre')).toBeInTheDocument()
  })

  it('text / cloze / reconstruction / verb を連続で解いて結果を出す', async () => {
    mockCreate.mockResolvedValue(session([TEXT, CLOZE, RECON, VERB_EX]))
    mockSubmit
      .mockResolvedValueOnce(okFeedback('livre', 'livre'))
      .mockResolvedValueOnce(
        okFeedback('rendu compte', 'rendu compte', {
          source_context: 'Je me suis ____.',
          explanation_ja: 'よく使う',
        }),
      )
      .mockResolvedValueOnce(
        okFeedback('se rendre compte de', ['se', 'rendre', 'compte', 'de'], {
          explanation_ja: 'よく使う',
        }),
      )
      .mockResolvedValueOnce(
        okFeedback('parle', 'parle', { explanation_ja: null, meaning_ja: null }),
      )

    render(<PracticeSessionFlow sourceId="src-1" questionCount={4} onExit={() => {}} />)

    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'livre')
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

    await screen.findByText('穴埋め')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'rendu compte')
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
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'parle')
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('✓ 正解')
    await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))

    await screen.findByText('セッション結果')
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('正解')).toBeInTheDocument()
    expect(mockCreate).toHaveBeenCalledWith({ source_id: 'src-1', question_count: 4 })
  })

  it('不正解でも correct answer / meaning を出し、結果に不正解数を載せる', async () => {
    mockCreate.mockResolvedValue(session([CHOICE]))
    mockSubmit.mockResolvedValue({
      correct: false,
      correct_answer: '本',
      given: '家',
      explanation_ja: '読むもの',
      source_context: null,
      meaning_ja: null,
      canonical_form: null,
    })
    render(<PracticeSessionFlow questionCount={1} onExit={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: '家' }))
    await screen.findByText('✗ 不正解')
    expect(screen.getByText(/正解:/)).toBeInTheDocument()
    expect(screen.getByText('読むもの')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))
    await screen.findByText('セッション結果')
    expect(screen.getByText('0%')).toBeInTheDocument()
    expect(screen.getByText('誤答した問題')).toBeInTheDocument()
  })

  it('回答送信失敗時は現在問題を失わない', async () => {
    mockCreate.mockResolvedValue(session([TEXT]))
    mockSubmit.mockRejectedValue(new ApiError(500, { detail: 'boom' }))
    render(<PracticeSessionFlow questionCount={1} onExit={() => {}} />)

    await screen.findByPlaceholderText('回答を入力...')
    await userEvent.type(screen.getByPlaceholderText('回答を入力...'), 'livre')
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveValue('livre')
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.queryByText('セッション結果')).not.toBeInTheDocument()
  })

  it('0件なら練習できる項目がないと案内する', async () => {
    mockCreate.mockResolvedValue(session([]))
    const onExit = vi.fn()
    render(<PracticeSessionFlow questionCount={5} onExit={onExit} />)

    await screen.findByText('練習できる学習項目がありません。候補を採用してから学習してください')
    await userEvent.click(screen.getByRole('button', { name: '戻る' }))
    expect(onExit).toHaveBeenCalled()
  })

  it('開始失敗から再試行できる', async () => {
    mockCreate
      .mockRejectedValueOnce(new ApiError(500))
      .mockResolvedValueOnce(session([CHOICE]))
    render(<PracticeSessionFlow questionCount={5} onExit={() => {}} />)

    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByText('意味')
  })
})

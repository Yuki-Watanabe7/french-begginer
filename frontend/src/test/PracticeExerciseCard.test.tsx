import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createRef } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PracticeExerciseCard } from '../components/PracticeExerciseCard'
import type { ExerciseFeedback, ExerciseView, LearningItem } from '../types'

let mockTTSError: string | null = null
const mockPlay = vi.fn()

vi.mock('../hooks/useTTS', () => ({
  useTTS: () => ({
    play: mockPlay,
    isLoading: false,
    error: mockTTSError,
    clearError: vi.fn(),
  }),
}))

const ITEM: LearningItem = {
  id: 'item-1',
  item_type: 'vocabulary',
  canonical_form: 'livre',
  meaning_ja: '本',
  explanation_ja: '読むもの',
  level: 'A1',
  source_refs: [],
  created_at: '2026-08-24T12:00:00+00:00',
  status: 'active',
}

function choiceExercise(): ExerciseView {
  return {
    learning_item_id: 'item-1',
    exercise_type: 'meaning_recognition',
    skill_direction: 'recognition',
    prompt: '次のフランス語の意味を選んでください。\n\nlivre',
    response_kind: 'choice',
    options: ['本', '家', '猫', '犬'],
    source_context: null,
    exercise_version: 'exercise-v1',
  }
}

function textExercise(type: ExerciseView['exercise_type'] = 'ja_to_fr'): ExerciseView {
  return {
    learning_item_id: 'item-1',
    exercise_type: type,
    skill_direction: 'production',
    prompt: '次の意味をフランス語で書いてください。\n\n本',
    response_kind: 'text',
    options: null,
    source_context: null,
    exercise_version: 'exercise-v1',
  }
}

function clozeExercise(): ExerciseView {
  return {
    learning_item_id: 'item-1',
    exercise_type: 'cloze',
    skill_direction: 'production',
    prompt: '次の空欄に入るフランス語を、原文のまま書いてください。\n\nJe me suis ____ qu\'il fallait.',
    response_kind: 'text',
    options: null,
    source_context: 'Je me suis ____ qu\'il fallait.',
    exercise_version: 'exercise-v1',
  }
}

function reconstructionExercise(): ExerciseView {
  return {
    learning_item_id: 'item-2',
    exercise_type: 'expression_reconstruction',
    skill_direction: 'production',
    prompt: '次の語を正しい順に並べて、表現を完成させてください。',
    response_kind: 'reconstruction',
    options: ['compte', 'se', 'de', 'rendre'],
    source_context: null,
    exercise_version: 'exercise-v1',
  }
}

function verbExercise(): ExerciseView {
  return {
    learning_item_id: 'item-3',
    exercise_type: 'verb_conjugation',
    skill_direction: 'production',
    prompt: '次の動詞を、指定された時制・主語で活用してください。\n\n動詞: parler\n時制: présent\n主語: je',
    response_kind: 'text',
    options: null,
    source_context: null,
    exercise_version: 'exercise-v1',
  }
}

function feedback(overrides: Partial<ExerciseFeedback> = {}): ExerciseFeedback {
  return {
    correct: true,
    correct_answer: '本',
    given: '本',
    explanation_ja: '読むもの',
    source_context: null,
    meaning_ja: '本',
    canonical_form: 'livre',
    ...overrides,
  }
}

function renderCard(overrides: Partial<React.ComponentProps<typeof PracticeExerciseCard>> = {}) {
  const defaults: React.ComponentProps<typeof PracticeExerciseCard> = {
    exercise: choiceExercise(),
    item: ITEM,
    input: '',
    reconstruction: [],
    feedback: null,
    submitting: false,
    submitError: null,
    inputRef: createRef<HTMLInputElement>(),
    questionNum: 1,
    sessionTotal: 5,
    onInputChange: vi.fn(),
    onReconstructionChange: vi.fn(),
    onSubmit: vi.fn(),
    onChoice: vi.fn(),
    onNext: vi.fn(),
  }
  return render(<PracticeExerciseCard {...defaults} {...overrides} />)
}

beforeEach(() => {
  mockTTSError = null
  mockPlay.mockReset()
})

describe('PracticeExerciseCard — choice', () => {
  it('進捗と未選択の選択肢を表示する', () => {
    renderCard({ questionNum: 2, sessionTotal: 5 })
    expect(screen.getByText('2 / 5')).toBeInTheDocument()
    expect(screen.getByText('意味')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '本' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: '家' })).toBeInTheDocument()
  })

  it('選択肢タップで onChoice が呼ばれる', async () => {
    const onChoice = vi.fn()
    renderCard({ onChoice })
    await userEvent.click(screen.getByRole('button', { name: '本' }))
    expect(onChoice).toHaveBeenCalledWith('本')
  })

  it('回答後は正誤と正解・意味・解説を出す', () => {
    renderCard({
      feedback: feedback({ correct: false, given: '家', correct_answer: '本' }),
    })
    expect(screen.getByText('✗ 不正解')).toBeInTheDocument()
    expect(screen.getByText(/正解:/)).toBeInTheDocument()
    expect(screen.getByText('読むもの')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '本' })).toBeDisabled()
  })
})

describe('PracticeExerciseCard — text / cloze / verb', () => {
  it('text 入力と判定、Enter 送信ができる', async () => {
    const onInputChange = vi.fn()
    const onSubmit = vi.fn()
    renderCard({
      exercise: textExercise(),
      input: 'livre',
      onInputChange,
      onSubmit,
    })
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveAttribute('autocomplete', 'off')
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    expect(onSubmit).toHaveBeenCalled()
    fireEvent.keyDown(screen.getByPlaceholderText('回答を入力...'), { key: 'Enter' })
    expect(onSubmit).toHaveBeenCalledTimes(2)
  })

  it('空入力では判定できない', () => {
    renderCard({ exercise: textExercise(), input: '  ' })
    expect(screen.getByRole('button', { name: '判定する' })).toBeDisabled()
  })

  it('cloze の正解と出典を表示する', () => {
    renderCard({
      exercise: clozeExercise(),
      feedback: feedback({
        correct: true,
        correct_answer: 'rendu compte',
        given: 'rendu compte',
        source_context: 'Je me suis ____ qu\'il fallait.',
        meaning_ja: '〜に気づく',
        canonical_form: 'se rendre compte de',
      }),
    })
    expect(screen.getByText('✓ 正解')).toBeInTheDocument()
    expect(screen.getByText('rendu compte')).toBeInTheDocument()
    expect(screen.getByText('Je me suis ____ qu\'il fallait.')).toBeInTheDocument()
    expect(screen.getByText('se rendre compte de')).toHaveStyle({ overflowWrap: 'anywhere' })
  })

  it('verb conjugation の正解を表示する', () => {
    renderCard({
      exercise: verbExercise(),
      item: { ...ITEM, item_type: 'conjugation', canonical_form: 'parler', meaning_ja: '話す' },
      feedback: feedback({
        correct: true,
        correct_answer: 'parle',
        given: 'parle',
        meaning_ja: '話す',
        canonical_form: 'parler',
        explanation_ja: null,
      }),
    })
    expect(screen.getByText('活用')).toBeInTheDocument()
    expect(screen.getByText('parle')).toBeInTheDocument()
    expect(screen.getByText('話す')).toBeInTheDocument()
  })

  it('判定後の Enter で次へ進む', () => {
    const onNext = vi.fn()
    renderCard({
      exercise: textExercise(),
      feedback: feedback({ correct_answer: 'livre', given: 'livre' }),
      onNext,
    })
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(onNext).toHaveBeenCalled()
  })
})

describe('PracticeExerciseCard — reconstruction', () => {
  it('タップで語を並べ、判定できる', async () => {
    const onChange = vi.fn()
    const onSubmit = vi.fn()
    renderCard({
      exercise: reconstructionExercise(),
      reconstruction: [1, 3, 0, 2],
      onReconstructionChange: onChange,
      onSubmit,
    })
    expect(screen.getByRole('button', { name: '判定する' })).not.toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '判定する' }))
    expect(onSubmit).toHaveBeenCalled()
    expect(screen.getByLabelText('並べた語')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'se' })).toHaveStyle({ minHeight: '44px' })
  })

  it('未完成なら判定できない', () => {
    renderCard({
      exercise: reconstructionExercise(),
      reconstruction: [1],
    })
    expect(screen.getByRole('button', { name: '判定する' })).toBeDisabled()
  })

  it('プールの語をタップすると onReconstructionChange が呼ばれる', async () => {
    const onChange = vi.fn()
    renderCard({
      exercise: reconstructionExercise(),
      reconstruction: [],
      onReconstructionChange: onChange,
    })
    await userEvent.click(screen.getByRole('button', { name: 'se' }))
    expect(onChange).toHaveBeenCalledWith([1])
  })
})

describe('PracticeExerciseCard — 送信失敗と TTS', () => {
  it('送信失敗時も現在の問題を残す', () => {
    renderCard({
      exercise: textExercise(),
      input: 'livre',
      submitError: '判定に失敗しました。通信環境を確認して再度お試しください',
    })
    expect(screen.getByPlaceholderText('回答を入力...')).toHaveValue('livre')
    expect(screen.getByRole('alert')).toHaveTextContent('判定に失敗しました')
    expect(screen.getByRole('button', { name: '判定する' })).toBeInTheDocument()
  })

  it('TTS 失敗しても次へ進める', async () => {
    mockTTSError = '音声を読み込めませんでした'
    const onNext = vi.fn()
    renderCard({
      exercise: textExercise(),
      item: ITEM,
      feedback: feedback({ correct_answer: 'livre', given: 'livre' }),
      onNext,
    })
    expect(screen.getByRole('alert')).toHaveTextContent('音声を読み込めませんでした')
    await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
    expect(onNext).toHaveBeenCalled()
  })

  it('最後の問題では結果を見るラベルになる', () => {
    renderCard({
      feedback: feedback(),
      questionNum: 5,
      sessionTotal: 5,
    })
    expect(screen.getByRole('button', { name: '結果を見る →' })).toBeInTheDocument()
  })

  it('長い出典は折り返す', () => {
    renderCard({
      exercise: clozeExercise(),
      feedback: feedback({
        source_context: 'A'.repeat(200),
        correct_answer: 'rendu',
      }),
    })
    expect(screen.getByText('A'.repeat(200))).toHaveStyle({
      overflowWrap: 'anywhere',
      whiteSpace: 'pre-wrap',
    })
  })
})

import { describe, it, expect, vi } from 'vitest'
import { createRef } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuizCard } from '../components/QuizCard'
import type { Question, AnswerResult } from '../types'

const Q: Question = { verb: 'parler', tense: 'présent', pronoun: 'je' }
const CORRECT: AnswerResult = { correct: true, expected: 'parle', given: 'parle' }
const INCORRECT: AnswerResult = { correct: false, expected: 'parle', given: 'parles' }

function renderCard(overrides: Partial<React.ComponentProps<typeof QuizCard>> = {}) {
  const defaults: React.ComponentProps<typeof QuizCard> = {
    question: Q,
    input: '',
    result: null,
    inputRef: createRef<HTMLInputElement>(),
    onInputChange: vi.fn(),
    onSubmit: vi.fn(),
    onNext: vi.fn(),
    questionNum: 1,
    sessionTotal: 5,
    isReviewPhase: false,
    nextLabel: '次の問題 →',
  }
  return render(<QuizCard {...defaults} {...overrides} />)
}

describe('QuizCard', () => {
  describe('問題表示', () => {
    it('動詞・人称代名詞・時制が表示される', () => {
      renderCard()
      expect(screen.getByText('parler')).toBeInTheDocument()
      expect(screen.getByText('je')).toBeInTheDocument()
      expect(screen.getByText('présent')).toBeInTheDocument()
    })

    it('進捗カウンターが表示される', () => {
      renderCard({ questionNum: 3, sessionTotal: 5 })
      expect(screen.getByText('3 / 5')).toBeInTheDocument()
    })

    it('復習フェーズでは「復習」バッジと「復習中」が表示される', () => {
      renderCard({ isReviewPhase: true })
      expect(screen.getByText('復習')).toBeInTheDocument()
      expect(screen.getByText('復習中')).toBeInTheDocument()
    })
  })

  describe('入力属性', () => {
    it('入力欄に予測候補抑止属性が設定されている', () => {
      renderCard()
      const input = screen.getByPlaceholderText('活用形を入力...')
      expect(input).toHaveAttribute('autocomplete', 'off')
      expect(input).toHaveAttribute('autocorrect', 'off')
      expect(input).toHaveAttribute('autocapitalize', 'none')
      expect(input).toHaveAttribute('spellcheck', 'false')
    })
  })

  describe('回答入力', () => {
    it('入力欄への入力でonInputChangeが呼ばれる', async () => {
      const onInputChange = vi.fn()
      renderCard({ onInputChange })
      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'a')
      expect(onInputChange).toHaveBeenCalled()
    })

    it('入力が空のとき判定ボタンが無効化されている', () => {
      renderCard({ input: '' })
      expect(screen.getByRole('button', { name: '判定する' })).toBeDisabled()
    })

    it('入力があるとき判定ボタンが有効になる', () => {
      renderCard({ input: 'parle' })
      expect(screen.getByRole('button', { name: '判定する' })).not.toBeDisabled()
    })

    it('入力があるとき判定ボタンをクリックするとonSubmitが呼ばれる', async () => {
      const onSubmit = vi.fn()
      renderCard({ input: 'parle', onSubmit })
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      expect(onSubmit).toHaveBeenCalled()
    })
  })

  describe('正解フィードバック', () => {
    it('正解時に「✓ 正解」が表示される', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByText('✓ 正解')).toBeInTheDocument()
    })

    it('正解時に判定ボタンが非表示になる', () => {
      renderCard({ result: CORRECT })
      expect(screen.queryByRole('button', { name: '判定する' })).not.toBeInTheDocument()
    })

    it('正解時に次の問題ボタンが表示される', () => {
      renderCard({ result: CORRECT, nextLabel: '次の問題 →' })
      expect(screen.getByRole('button', { name: '次の問題 →' })).toBeInTheDocument()
    })
  })

  describe('不正解フィードバック', () => {
    it('不正解時に「✗ 不正解」が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('✗ 不正解')).toBeInTheDocument()
    })

    it('不正解時に正解が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('正解:')).toBeInTheDocument()
      expect(screen.getByText('parle')).toBeInTheDocument()
    })

    it('不正解時に次の問題ボタンをクリックするとonNextが呼ばれる', async () => {
      const onNext = vi.fn()
      renderCard({ result: INCORRECT, onNext, nextLabel: '次の問題 →' })
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
      expect(onNext).toHaveBeenCalled()
    })
  })

  describe('Enterキー操作', () => {
    it('入力中にEnterを押すとonSubmitが呼ばれる', async () => {
      const onSubmit = vi.fn()
      renderCard({ input: 'parle', onSubmit })
      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), '{Enter}')
      expect(onSubmit).toHaveBeenCalled()
    })

    it('判定後にEnterを押すとonNextが呼ばれる', () => {
      const onNext = vi.fn()
      renderCard({ result: CORRECT, onNext })
      fireEvent.keyDown(window, { key: 'Enter' })
      expect(onNext).toHaveBeenCalled()
    })

    it('未判定状態ではEnterキーでonNextが呼ばれない', () => {
      const onNext = vi.fn()
      renderCard({ result: null, input: 'parle', onNext })
      fireEvent.keyDown(window, { key: 'Enter' })
      expect(onNext).not.toHaveBeenCalled()
    })

    it('IME composition中のEnterでは次へ進まない', () => {
      const onNext = vi.fn()
      renderCard({ result: CORRECT, onNext })
      fireEvent.keyDown(window, { key: 'Enter', isComposing: true })
      expect(onNext).not.toHaveBeenCalled()
    })
  })
})

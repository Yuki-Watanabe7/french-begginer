import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SessionResult } from '../components/SessionResult'
import type { WrongAnswer } from '../types'

const WRONG: WrongAnswer = {
  verb: 'parler',
  tense: 'présent',
  pronoun: 'je',
  correctAnswer: 'parle',
  userAnswer: 'parles',
}

function renderResult(overrides: Partial<React.ComponentProps<typeof SessionResult>> = {}) {
  const defaults: React.ComponentProps<typeof SessionResult> = {
    firstCorrectCount: 5,
    reviewCorrectCount: 0,
    unresolvedCount: 0,
    wrongAnswers: [],
    normalSessionTotal: 5,
    onRetry: vi.fn(),
    onBackToSetup: vi.fn(),
  }
  return render(<SessionResult {...defaults} {...overrides} />)
}

describe('SessionResult', () => {
  describe('結果画面の表示', () => {
    it('「セッション結果」見出しが表示される', () => {
      renderResult()
      expect(screen.getByText('セッション結果')).toBeInTheDocument()
    })

    it('初回正答率が表示される（5問中5問正解 = 100%）', () => {
      renderResult({ firstCorrectCount: 5, normalSessionTotal: 5 })
      expect(screen.getByText('100%')).toBeInTheDocument()
      expect(screen.getByText('初回正答率')).toBeInTheDocument()
    })

    it('初回正答率が計算される（5問中4問正解 = 80%）', () => {
      renderResult({ firstCorrectCount: 4, normalSessionTotal: 5, unresolvedCount: 1, wrongAnswers: [WRONG] })
      expect(screen.getByText('80%')).toBeInTheDocument()
    })

    it('合計問数が表示される', () => {
      renderResult({ normalSessionTotal: 5 })
      expect(screen.getByText('合計')).toBeInTheDocument()
    })

    it('初回正解の統計が表示される', () => {
      renderResult({ firstCorrectCount: 4, normalSessionTotal: 5, unresolvedCount: 1, wrongAnswers: [WRONG] })
      expect(screen.getByText('初回正解')).toBeInTheDocument()
    })

    it('未解決の統計が表示される', () => {
      renderResult({ unresolvedCount: 1, wrongAnswers: [WRONG] })
      expect(screen.getByText('未解決')).toBeInTheDocument()
    })
  })

  describe('誤答一覧', () => {
    it('誤答がある場合に「初回誤答問題」セクションが表示される', () => {
      renderResult({ wrongAnswers: [WRONG], firstCorrectCount: 4, unresolvedCount: 1 })
      expect(screen.getByText('初回誤答問題')).toBeInTheDocument()
    })

    it('誤答の動詞・時制・人称・正解・回答が表示される', () => {
      renderResult({ wrongAnswers: [WRONG], firstCorrectCount: 4, unresolvedCount: 1 })
      expect(screen.getByText('parler')).toBeInTheDocument()
      expect(screen.getByText('présent')).toBeInTheDocument()
      expect(screen.getByText('je')).toBeInTheDocument()
      expect(screen.getByText('parle')).toBeInTheDocument()
      expect(screen.getByText('parles')).toBeInTheDocument()
    })

    it('誤答がない場合は誤答一覧が表示されない', () => {
      renderResult({ wrongAnswers: [], unresolvedCount: 0 })
      expect(screen.queryByText('初回誤答問題')).not.toBeInTheDocument()
    })

    it('複数の誤答がすべて表示される', () => {
      const wrong2: WrongAnswer = {
        verb: 'aimer',
        tense: 'présent',
        pronoun: 'tu',
        correctAnswer: 'aimes',
        userAnswer: 'aime',
      }
      renderResult({ wrongAnswers: [WRONG, wrong2], firstCorrectCount: 3, unresolvedCount: 2 })
      expect(screen.getByText('parler')).toBeInTheDocument()
      expect(screen.getByText('aimer')).toBeInTheDocument()
    })
  })

  describe('復習あり', () => {
    it('誤答がある場合に復習正解の統計が表示される', () => {
      renderResult({
        wrongAnswers: [WRONG],
        firstCorrectCount: 4,
        reviewCorrectCount: 1,
        unresolvedCount: 0,
      })
      expect(screen.getByText('復習正解')).toBeInTheDocument()
    })

    it('誤答がない場合に復習正解の統計が表示されない', () => {
      renderResult({ wrongAnswers: [], reviewCorrectCount: 0, unresolvedCount: 0 })
      expect(screen.queryByText('復習正解')).not.toBeInTheDocument()
    })
  })

  describe('ボタン操作', () => {
    it('「もう一度挑戦」ボタンをクリックするとonRetryが呼ばれる', async () => {
      const onRetry = vi.fn()
      renderResult({ onRetry })
      await userEvent.click(screen.getByRole('button', { name: 'もう一度挑戦' }))
      expect(onRetry).toHaveBeenCalled()
    })

    it('「モード選択に戻る」ボタンをクリックするとonBackToSetupが呼ばれる', async () => {
      const onBackToSetup = vi.fn()
      renderResult({ onBackToSetup })
      await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
      expect(onBackToSetup).toHaveBeenCalled()
    })
  })
})

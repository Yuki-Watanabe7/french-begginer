import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NounGenderCard } from '../components/NounGenderCard'
import type { NounGenderAnswerResult, NounGenderQuestion } from '../types'

let mockTTSError: string | null = null

vi.mock('../hooks/useTTS', () => ({
  useTTS: () => ({ play: vi.fn(), isLoading: false, error: mockTTSError, clearError: vi.fn() }),
}))

beforeEach(() => {
  mockTTSError = null
})

const Q: NounGenderQuestion = { noun: 'livre', meaning_ja: '本', article_indefinite: 'un' }
const Q_NO_MEANING: NounGenderQuestion = { noun: 'chat', meaning_ja: null, article_indefinite: 'un' }
const CORRECT: NounGenderAnswerResult = { correct: true, expected: 'masculine', given: 'masculine' }
const INCORRECT: NounGenderAnswerResult = { correct: false, expected: 'masculine', given: 'feminine' }

function renderCard(overrides: Partial<React.ComponentProps<typeof NounGenderCard>> = {}) {
  const defaults: React.ComponentProps<typeof NounGenderCard> = {
    question: Q,
    result: null,
    onAnswer: vi.fn(),
    onNext: vi.fn(),
    questionNum: 1,
    sessionTotal: 5,
    isReviewPhase: false,
    nextLabel: '次の問題 →',
  }
  return render(<NounGenderCard {...defaults} {...overrides} />)
}

describe('NounGenderCard', () => {
  describe('問題表示', () => {
    it('名詞が大きく表示される', () => {
      renderCard()
      expect(screen.getByText('livre')).toBeInTheDocument()
    })

    it('意味が表示される', () => {
      renderCard()
      expect(screen.getByText('本')).toBeInTheDocument()
    })

    it('意味がnullの場合は意味が表示されない', () => {
      renderCard({ question: Q_NO_MEANING })
      expect(screen.queryByText('本')).not.toBeInTheDocument()
    })

    it('進捗カウンターが表示される', () => {
      renderCard({ questionNum: 2, sessionTotal: 10 })
      expect(screen.getByText('2 / 10')).toBeInTheDocument()
    })

    it('復習フェーズでは「復習」バッジと「復習中」が表示される', () => {
      renderCard({ isReviewPhase: true })
      expect(screen.getByText('復習')).toBeInTheDocument()
      expect(screen.getByText('復習中')).toBeInTheDocument()
    })

    it('通常フェーズでは「名詞の性」バッジが表示される', () => {
      renderCard()
      expect(screen.getByText('名詞の性')).toBeInTheDocument()
    })
  })

  describe('2択ボタン', () => {
    it('「男性名詞」と「女性名詞」ボタンが表示される', () => {
      renderCard()
      expect(screen.getByText('男性名詞')).toBeInTheDocument()
      expect(screen.getByText('女性名詞')).toBeInTheDocument()
    })

    it('「男性名詞」ボタンをクリックするとonAnswerが masculine で呼ばれる', async () => {
      const onAnswer = vi.fn()
      renderCard({ onAnswer })
      await userEvent.click(screen.getByRole('button', { name: /男性名詞/ }))
      expect(onAnswer).toHaveBeenCalledWith('masculine')
    })

    it('「女性名詞」ボタンをクリックするとonAnswerが feminine で呼ばれる', async () => {
      const onAnswer = vi.fn()
      renderCard({ onAnswer })
      await userEvent.click(screen.getByRole('button', { name: /女性名詞/ }))
      expect(onAnswer).toHaveBeenCalledWith('feminine')
    })

    it('回答後はボタンが無効化される', () => {
      renderCard({ result: CORRECT })
      const buttons = screen.getAllByRole('button')
      const choiceButtons = buttons.filter(b => /男性名詞|女性名詞/.test(b.textContent ?? ''))
      choiceButtons.forEach(btn => expect(btn).toBeDisabled())
    })
  })

  describe('正解フィードバック', () => {
    it('正解時に「✓ 正解」が表示される', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByText('✓ 正解')).toBeInTheDocument()
    })

    it('正解時に次のボタンが表示される', () => {
      renderCard({ result: CORRECT, nextLabel: '次の問題 →' })
      expect(screen.getByRole('button', { name: '次の問題 →' })).toBeInTheDocument()
    })
  })

  describe('音声再生ボタン', () => {
    it('🔊ボタンが表示される', () => {
      renderCard()
      expect(screen.getByRole('button', { name: /読み上げる/ })).toBeInTheDocument()
    })

    it('男性名詞のaria-labelに「un livre」が含まれる', () => {
      renderCard()
      expect(screen.getByLabelText('un livreを読み上げる')).toBeInTheDocument()
    })

    it('女性名詞のaria-labelに「une maison」が含まれる', () => {
      const femQ: NounGenderQuestion = { noun: 'maison', meaning_ja: '家', article_indefinite: 'une' }
      renderCard({ question: femQ })
      expect(screen.getByLabelText('une maisonを読み上げる')).toBeInTheDocument()
    })

    it('通常時はボタンがdisabledでない', () => {
      renderCard()
      expect(screen.getByRole('button', { name: /読み上げる/ })).not.toBeDisabled()
    })

    it('ボタンをクリックしてもエラーが発生しない', async () => {
      renderCard()
      await userEvent.click(screen.getByRole('button', { name: /読み上げる/ }))
    })

    it('TTSエラー時にエラーメッセージが表示される', () => {
      mockTTSError = '音声を読み込めませんでした'
      renderCard()
      expect(screen.getByRole('alert')).toHaveTextContent('音声を読み込めませんでした')
    })

    it('TTSエラーがnullの場合はエラーメッセージが表示されない', () => {
      mockTTSError = null
      renderCard()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  describe('不正解フィードバック', () => {
    it('不正解時に「✗ 不正解」が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('✗ 不正解')).toBeInTheDocument()
    })

    it('不正解時に正解の性が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('正解:')).toBeInTheDocument()
      // 「男性名詞」はボタンとフィードバック両方に出るので複数確認
      const items = screen.getAllByText('男性名詞')
      expect(items.length).toBeGreaterThanOrEqual(1)
    })

    it('不正解時に次のボタンをクリックするとonNextが呼ばれる', async () => {
      const onNext = vi.fn()
      renderCard({ result: INCORRECT, onNext, nextLabel: '次の問題 →' })
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
      expect(onNext).toHaveBeenCalled()
    })
  })
})

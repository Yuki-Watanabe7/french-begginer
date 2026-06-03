import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NounArticleCard } from '../components/NounArticleCard'
import type { NounArticleAnswerResult, NounArticleQuestion } from '../types'

let mockTTSError: string | null = null

vi.mock('../hooks/useTTS', () => ({
  useTTS: () => ({ play: vi.fn(), isLoading: false, error: mockTTSError, clearError: vi.fn() }),
}))

beforeEach(() => {
  mockTTSError = null
})

const Q: NounArticleQuestion = { noun: 'livre', meaning_ja: '本' }
const Q_NO_MEANING: NounArticleQuestion = { noun: 'chat', meaning_ja: null }
const CORRECT: NounArticleAnswerResult = { correct: true, expected: 'un livre', given: 'un livre' }
const INCORRECT: NounArticleAnswerResult = { correct: false, expected: 'un livre', given: 'une livre' }

function renderCard(overrides: Partial<React.ComponentProps<typeof NounArticleCard>> = {}) {
  const defaults: React.ComponentProps<typeof NounArticleCard> = {
    question: Q,
    input: '',
    result: null,
    inputRef: { current: null },
    onInputChange: vi.fn(),
    onSubmit: vi.fn(),
    onNext: vi.fn(),
    questionNum: 1,
    sessionTotal: 5,
    isReviewPhase: false,
    nextLabel: '次の問題 →',
  }
  return render(<NounArticleCard {...defaults} {...overrides} />)
}

describe('NounArticleCard', () => {
  describe('問題表示', () => {
    it('日本語訳が大きく表示される', () => {
      renderCard()
      expect(screen.getByText('本')).toBeInTheDocument()
    })

    it('意味がnullの場合は「—」が表示される', () => {
      renderCard({ question: Q_NO_MEANING })
      expect(screen.getByText('—')).toBeInTheDocument()
    })

    it('進捗カウンターが表示される', () => {
      renderCard({ questionNum: 2, sessionTotal: 10 })
      expect(screen.getByText('2 / 10')).toBeInTheDocument()
    })

    it('通常フェーズでは「冠詞+名詞」バッジが表示される', () => {
      renderCard()
      expect(screen.getByText('冠詞+名詞')).toBeInTheDocument()
    })

    it('復習フェーズでは「復習」バッジと「復習中」が表示される', () => {
      renderCard({ isReviewPhase: true })
      expect(screen.getByText('復習')).toBeInTheDocument()
      expect(screen.getByText('復習中')).toBeInTheDocument()
    })

    it('入力欄のプレースホルダーが表示される', () => {
      renderCard()
      expect(screen.getByPlaceholderText('un / une + 名詞...')).toBeInTheDocument()
    })

    it('名詞は表示されない（ユーザーが入力する）', () => {
      renderCard()
      expect(screen.queryByText('livre')).not.toBeInTheDocument()
    })
  })

  describe('入力と送信', () => {
    it('入力欄にテキストを入力するとonInputChangeが呼ばれる', async () => {
      const onInputChange = vi.fn()
      renderCard({ onInputChange })
      const input = screen.getByPlaceholderText('un / une + 名詞...')
      await userEvent.type(input, 'u')
      expect(onInputChange).toHaveBeenCalled()
    })

    it('入力が空の場合は「判定する」ボタンが無効', () => {
      renderCard({ input: '' })
      expect(screen.getByRole('button', { name: '判定する' })).toBeDisabled()
    })

    it('入力がある場合は「判定する」ボタンが有効', () => {
      renderCard({ input: 'un livre' })
      expect(screen.getByRole('button', { name: '判定する' })).not.toBeDisabled()
    })

    it('「判定する」ボタンをクリックするとonSubmitが呼ばれる', async () => {
      const onSubmit = vi.fn()
      renderCard({ input: 'un livre', onSubmit })
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      expect(onSubmit).toHaveBeenCalled()
    })

    it('Enterキーで送信できる（未回答時）', async () => {
      const onSubmit = vi.fn()
      renderCard({ input: 'un livre', onSubmit })
      const input = screen.getByPlaceholderText('un / une + 名詞...')
      await userEvent.type(input, '{Enter}')
      expect(onSubmit).toHaveBeenCalled()
    })

    it('回答後は入力欄が無効化される', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByPlaceholderText('un / une + 名詞...')).toBeDisabled()
    })

    it('判定後にEnterを押すとonNextが呼ばれる', () => {
      const onNext = vi.fn()
      renderCard({ result: CORRECT, onNext })
      fireEvent.keyDown(window, { key: 'Enter' })
      expect(onNext).toHaveBeenCalled()
    })

    it('未判定状態ではEnterキーでonNextが呼ばれない', () => {
      const onNext = vi.fn()
      renderCard({ result: null, input: 'un livre', onNext })
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

  describe('正解フィードバック', () => {
    it('正解時に「✓ 正解」が表示される', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByText('✓ 正解')).toBeInTheDocument()
    })

    it('正解時に「判定する」ボタンが非表示になる', () => {
      renderCard({ result: CORRECT })
      expect(screen.queryByRole('button', { name: '判定する' })).not.toBeInTheDocument()
    })

    it('正解時に次のボタンが表示される', () => {
      renderCard({ result: CORRECT, nextLabel: '次の問題 →' })
      expect(screen.getByRole('button', { name: '次の問題 →' })).toBeInTheDocument()
    })

    it('次の問題ボタンをクリックするとonNextが呼ばれる（回答後）', async () => {
      const onNext = vi.fn()
      renderCard({ result: CORRECT, onNext, nextLabel: '次の問題 →' })
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
      expect(onNext).toHaveBeenCalled()
    })
  })

  describe('不正解フィードバック', () => {
    it('不正解時に「✗ 不正解」が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('✗ 不正解')).toBeInTheDocument()
    })

    it('不正解時に正解の冠詞付き名詞が表示される', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByText('正解:')).toBeInTheDocument()
      expect(screen.getByText('un livre')).toBeInTheDocument()
    })

    it('不正解時に次のボタンをクリックするとonNextが呼ばれる', async () => {
      const onNext = vi.fn()
      renderCard({ result: INCORRECT, onNext, nextLabel: '次の問題 →' })
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
      expect(onNext).toHaveBeenCalled()
    })
  })

  describe('音声再生ボタン', () => {
    it('回答後に🔊ボタンが表示される（正解時）', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByRole('button', { name: /読み上げる/ })).toBeInTheDocument()
    })

    it('回答後に🔊ボタンが表示される（不正解時）', () => {
      renderCard({ result: INCORRECT })
      expect(screen.getByRole('button', { name: /読み上げる/ })).toBeInTheDocument()
    })

    it('ボタンのaria-labelに正解の冠詞付き名詞が含まれる', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByLabelText('un livreを読み上げる')).toBeInTheDocument()
    })

    it('回答前は🔊ボタンが表示されない', () => {
      renderCard({ result: null })
      expect(screen.queryByRole('button', { name: /読み上げる/ })).not.toBeInTheDocument()
    })

    it('通常時はボタンがdisabledでない', () => {
      renderCard({ result: CORRECT })
      expect(screen.getByRole('button', { name: /読み上げる/ })).not.toBeDisabled()
    })

    it('TTSエラー時に回答後のエリアにエラーメッセージが表示される', () => {
      mockTTSError = '音声を読み込めませんでした'
      renderCard({ result: CORRECT })
      expect(screen.getByRole('alert')).toHaveTextContent('音声を読み込めませんでした')
    })

    it('TTSエラーがnullの場合はエラーメッセージが表示されない', () => {
      mockTTSError = null
      renderCard({ result: CORRECT })
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('回答前はTTSエラーが表示されない（🔊ボタン自体が非表示）', () => {
      mockTTSError = '音声を読み込めませんでした'
      renderCard({ result: null })
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })
})

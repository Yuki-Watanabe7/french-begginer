import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import * as client from '../api/client'
import type { NounGenderAnswerResult, NounGenderQuestion } from '../types'

vi.mock('../api/client')

const mockFetchNoun = vi.mocked(client.fetchNounSessionQuestions)
const mockCheckNoun = vi.mocked(client.checkNounAnswer)

const Q: NounGenderQuestion = { noun: 'livre', meaning_ja: '本' }
const CORRECT: NounGenderAnswerResult = { correct: true, expected: 'masculine', given: 'masculine' }

async function navigateToNounFilter() {
  render(<App />)
  await userEvent.click(screen.getByText('名詞の性クイズ'))
}

async function navigateToNounQuestion(filterLabel = '全名詞') {
  await navigateToNounFilter()
  await userEvent.click(screen.getByText(filterLabel))
  await userEvent.click(screen.getByText('5問'))
  await screen.findByText('livre')
}

describe('名詞クイズ — フィルタ選択フロー', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  describe('カテゴリ選択画面', () => {
    it('名詞モード選択後にカテゴリ選択画面が表示される', async () => {
      await navigateToNounFilter()
      expect(screen.getByText('出題範囲を選択')).toBeInTheDocument()
      expect(screen.getByText('全名詞')).toBeInTheDocument()
      expect(screen.getByText('基本名詞')).toBeInTheDocument()
    })

    it('「モード選択に戻る」でモード選択画面に戻る', async () => {
      await navigateToNounFilter()
      await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
      expect(screen.getByText('練習モードを選択')).toBeInTheDocument()
    })
  })

  describe('フィルタなし（全名詞）', () => {
    it('「全名詞」選択後、問題数選択画面に進める', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounFilter()
      await userEvent.click(screen.getByText('全名詞'))
      expect(screen.getByText('出題数を選択')).toBeInTheDocument()
    })

    it('「全名詞」選択後のAPI呼び出しにクエリパラメータが含まれない', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounQuestion('全名詞')
      expect(mockFetchNoun).toHaveBeenCalledWith(5, {})
    })
  })

  describe('フィルタあり（基本名詞）', () => {
    it('「基本名詞」選択後のAPI呼び出しに level=basic が渡される', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounQuestion('基本名詞')
      expect(mockFetchNoun).toHaveBeenCalledWith(5, { level: 'basic' })
    })
  })

  describe('フィルタあり（カテゴリ）', () => {
    it('「食べ物」選択後のAPI呼び出しに category=food が渡される', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounQuestion('食べ物')
      expect(mockFetchNoun).toHaveBeenCalledWith(5, { category: 'food' })
    })

    it('「場所」選択後のAPI呼び出しに category=place が渡される', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounQuestion('場所')
      expect(mockFetchNoun).toHaveBeenCalledWith(5, { category: 'place' })
    })
  })

  describe('クイズ設定の「戻る」', () => {
    it('出題数選択画面の「戻る」でカテゴリ選択画面に戻る', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      await navigateToNounFilter()
      await userEvent.click(screen.getByText('全名詞'))
      expect(screen.getByText('出題数を選択')).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: '戻る' }))
      expect(screen.getByText('出題範囲を選択')).toBeInTheDocument()
    })
  })

  describe('セッション中のフィルタ維持', () => {
    it('セッション開始時に正しいフィルタでAPIが呼ばれる', async () => {
      mockFetchNoun.mockResolvedValue([Q, Q, Q, Q, Q])
      mockCheckNoun.mockResolvedValue(CORRECT)
      await navigateToNounQuestion('基本名詞')

      // セッション開始時に1回だけAPIが呼ばれ、正しいフィルタが渡されていること
      expect(mockFetchNoun).toHaveBeenCalledTimes(1)
      expect(mockFetchNoun).toHaveBeenCalledWith(5, { level: 'basic' })
    })
  })
})

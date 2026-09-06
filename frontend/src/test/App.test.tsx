import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import * as client from '../api/client'
import { fetchTutorSources, fetchReviewQueue, fetchTodayPlan } from '../api/tutor'
import type { Question, AnswerResult } from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'
import { EMPTY_TODAY_PLAN } from './todayPlanFixtures'

vi.mock('../api/client')
vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchReviewQueue: vi.fn(),
    fetchTodayPlan: vi.fn(),
  }
})

const mockFetch = vi.mocked(client.fetchSessionQuestions)
const mockCheck = vi.mocked(client.checkAnswer)
const mockListSources = vi.mocked(fetchTutorSources)
const mockReviewQueue = vi.mocked(fetchReviewQueue)
const mockTodayPlan = vi.mocked(fetchTodayPlan)

const Q: Question = { verb: 'parler', tense: 'présent', pronoun: 'je' }
const Q2: Question = { verb: 'aimer', tense: 'présent', pronoun: 'tu' }
const CORRECT: AnswerResult = { correct: true, expected: 'parle', given: 'parle' }
const INCORRECT: AnswerResult = { correct: false, expected: 'parle', given: 'parles' }

async function navigateToFirstQuestion() {
  mockFetch.mockResolvedValue([Q, Q, Q, Q, Q])
  render(<App />)
  await userEvent.click(screen.getByText('動詞活用練習'))
  await userEvent.click(screen.getByText('全動詞'))
  await userEvent.click(screen.getByText('次へ →'))
  await userEvent.click(screen.getByText('5問'))
  await screen.findByRole('button', { name: '判定する' })
}

describe('App — モード選択', () => {
  it('既存の練習モードと自分の教材が表示される', () => {
    render(<App />)
    expect(screen.getByText('動詞活用練習')).toBeInTheDocument()
    expect(screen.getByText('名詞の性クイズ')).toBeInTheDocument()
    expect(screen.getByText('冠詞付き名詞')).toBeInTheDocument()
    expect(screen.getByText('自分の教材')).toBeInTheDocument()
  })

  it('自分の教材からSource一覧へ進み、モード選択に戻れる', async () => {
    mockListSources.mockResolvedValueOnce([])
    mockReviewQueue.mockResolvedValueOnce(EMPTY_REVIEW_QUEUE)
    mockTodayPlan.mockResolvedValueOnce(EMPTY_TODAY_PLAN)
    render(<App />)
    await userEvent.click(screen.getByText('自分の教材'))
    await screen.findByText('まだ保存したテキストがありません')
    expect(screen.getByRole('button', { name: '新しいテキストを追加' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
    expect(screen.getByText('練習モードを選択')).toBeInTheDocument()
    expect(screen.getByText('動詞活用練習')).toBeInTheDocument()
  })
})

describe('App — 主要学習フロー', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  describe('問題表示', () => {
    it('動詞と人称代名詞が画面に表示される', async () => {
      await navigateToFirstQuestion()
      expect(screen.getByText('parler')).toBeInTheDocument()
      expect(screen.getByText('je')).toBeInTheDocument()
    })
  })

  describe('回答入力', () => {
    it('入力欄にテキストを入力できる', async () => {
      await navigateToFirstQuestion()
      const input = screen.getByPlaceholderText('活用形を入力...')
      await userEvent.type(input, 'parle')
      expect(input).toHaveValue('parle')
    })
  })

  describe('正解判定', () => {
    it('正しい回答を送信すると「✓ 正解」が表示される', async () => {
      mockCheck.mockResolvedValue(CORRECT)
      await navigateToFirstQuestion()
      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parle')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✓ 正解')
    })
  })

  describe('不正解判定', () => {
    it('誤った回答を送信すると「✗ 不正解」と正解が表示される', async () => {
      mockCheck.mockResolvedValue(INCORRECT)
      await navigateToFirstQuestion()
      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parles')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✗ 不正解')
      expect(screen.getByText('正解:')).toBeInTheDocument()
    })
  })

  describe('次問遷移', () => {
    it('正解後に「次の問題」ボタンをクリックすると次の問題に遷移する', async () => {
      mockFetch.mockResolvedValueOnce([Q, Q2, Q, Q, Q])
      mockCheck.mockResolvedValue(CORRECT)
      render(<App />)
      await userEvent.click(screen.getByText('動詞活用練習'))
      await userEvent.click(screen.getByText('全動詞'))
      await userEvent.click(screen.getByText('次へ →'))
      await userEvent.click(screen.getByText('5問'))
      await screen.findByText('parler')

      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parle')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✓ 正解')
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

      await screen.findByText('aimer')
    })

    it('不正解後に「次の問題」ボタンをクリックすると次の問題に遷移する', async () => {
      mockFetch.mockResolvedValueOnce([Q, Q2, Q, Q, Q])
      mockCheck.mockResolvedValue(INCORRECT)
      render(<App />)
      await userEvent.click(screen.getByText('動詞活用練習'))
      await userEvent.click(screen.getByText('全動詞'))
      await userEvent.click(screen.getByText('次へ →'))
      await userEvent.click(screen.getByText('5問'))
      await screen.findByText('parler')

      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parles')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✗ 不正解')
      await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))

      await screen.findByText('aimer')
    })
  })

  describe('結果画面表示・セッション終了', () => {
    it('5問すべて正解後にセッション結果画面へ遷移し正答率100%が表示される', async () => {
      mockFetch.mockResolvedValue([Q, Q, Q, Q, Q])
      mockCheck.mockResolvedValue(CORRECT)
      render(<App />)
      await userEvent.click(screen.getByText('動詞活用練習'))
      await userEvent.click(screen.getByText('全動詞'))
      await userEvent.click(screen.getByText('次へ →'))
      await userEvent.click(screen.getByText('5問'))
      await screen.findByRole('button', { name: '判定する' })

      for (let i = 0; i < 4; i++) {
        await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parle')
        await userEvent.click(screen.getByRole('button', { name: '判定する' }))
        await screen.findByText('✓ 正解')
        await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
        await screen.findByRole('button', { name: '判定する' })
      }

      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parle')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✓ 正解')
      await userEvent.click(screen.getByRole('button', { name: '結果を見る →' }))

      await screen.findByText('セッション結果')
      expect(screen.getByText('100%')).toBeInTheDocument()
      expect(screen.getByText('初回正答率')).toBeInTheDocument()
    })
  })

  describe('復習フェーズ遷移', () => {
    it('誤答がある場合にセッション終了後に復習フェーズへ遷移する', async () => {
      mockFetch.mockResolvedValue([Q, Q, Q, Q, Q])
      mockCheck
        .mockResolvedValueOnce(CORRECT)
        .mockResolvedValueOnce(CORRECT)
        .mockResolvedValueOnce(CORRECT)
        .mockResolvedValueOnce(CORRECT)
        .mockResolvedValueOnce(INCORRECT)
      render(<App />)
      await userEvent.click(screen.getByText('動詞活用練習'))
      await userEvent.click(screen.getByText('全動詞'))
      await userEvent.click(screen.getByText('次へ →'))
      await userEvent.click(screen.getByText('5問'))
      await screen.findByRole('button', { name: '判定する' })

      for (let i = 0; i < 4; i++) {
        await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parle')
        await userEvent.click(screen.getByRole('button', { name: '判定する' }))
        await screen.findByText('✓ 正解')
        await userEvent.click(screen.getByRole('button', { name: '次の問題 →' }))
        await screen.findByRole('button', { name: '判定する' })
      }

      await userEvent.type(screen.getByPlaceholderText('活用形を入力...'), 'parles')
      await userEvent.click(screen.getByRole('button', { name: '判定する' }))
      await screen.findByText('✗ 不正解')

      await userEvent.click(screen.getByRole('button', { name: '復習へ →' }))
      await screen.findByText('復習')
    })
  })
})

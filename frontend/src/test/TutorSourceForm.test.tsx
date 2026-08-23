import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorSourceForm } from '../components/TutorSourceForm'
import { ApiError, createTutorSource } from '../api/tutor'
import type { SourceDocument } from '../types'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    createTutorSource: vi.fn(),
  }
})

const mockCreate = vi.mocked(createTutorSource)

const SAVED: SourceDocument = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  content: "Il s'agit d'un article.",
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  metadata: { note: '新聞の社説' },
}

async function fillRequiredFields(
  title = 'Le Monde',
  content = "Il s'agit d'un article.",
) {
  await userEvent.type(screen.getByLabelText(/タイトル/), title)
  await userEvent.type(screen.getByLabelText(/本文/), content)
}

function renderForm(
  overrides: {
    onBack?: () => void
    onSaved?: (source: SourceDocument) => void
  } = {},
) {
  const onBack = overrides.onBack ?? vi.fn()
  const onSaved = overrides.onSaved ?? vi.fn()
  render(<TutorSourceForm onBack={onBack} onSaved={onSaved} />)
  return { onBack, onSaved }
}

describe('TutorSourceForm', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  describe('表示', () => {
    it('title / content / note の入力欄が表示される', () => {
      renderForm()

      expect(screen.getByLabelText(/タイトル/)).toBeInTheDocument()
      expect(screen.getByLabelText(/本文/)).toBeInTheDocument()
      expect(screen.getByLabelText(/メモ/)).toBeInTheDocument()
      expect(screen.getAllByText('必須')).toHaveLength(2)
    })

    it('本文欄はスマホ幅でも貼り付けやすい高さを持つ', () => {
      renderForm()
      expect(screen.getByLabelText(/本文/)).toHaveStyle({ minHeight: '40vh' })
    })
  })

  describe('validation', () => {
    it('空入力では保存されず、必須エラーを表示する', async () => {
      renderForm()

      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      expect(mockCreate).not.toHaveBeenCalled()
      expect(screen.getByText('タイトルを入力してください')).toBeInTheDocument()
      expect(screen.getByText('フランス語の本文を入力してください')).toBeInTheDocument()
    })

    it('whitespaceのみも空として扱い、APIを呼ばない', async () => {
      renderForm()

      await userEvent.type(screen.getByLabelText(/タイトル/), '   ')
      await userEvent.type(screen.getByLabelText(/本文/), '     ')
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      expect(mockCreate).not.toHaveBeenCalled()
      expect(screen.getByText('タイトルを入力してください')).toBeInTheDocument()
      expect(screen.getByText('フランス語の本文を入力してください')).toBeInTheDocument()
    })
  })

  describe('保存', () => {
    it('正常入力で createTutorSource が language=fr と note metadata で呼ばれる', async () => {
      mockCreate.mockResolvedValueOnce(SAVED)
      renderForm()

      await fillRequiredFields()
      await userEvent.type(screen.getByLabelText(/メモ/), '新聞の社説')
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      expect(mockCreate).toHaveBeenCalledWith({
        title: 'Le Monde',
        content: "Il s'agit d'un article.",
        language: 'fr',
        metadata: { note: '新聞の社説' },
      })
    })

    it('note未入力時は空の metadata を送る', async () => {
      mockCreate.mockResolvedValueOnce({ ...SAVED, metadata: {} })
      renderForm()

      await fillRequiredFields()
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      expect(mockCreate).toHaveBeenCalledWith({
        title: 'Le Monde',
        content: "Il s'agit d'un article.",
        language: 'fr',
        metadata: {},
      })
    })

    it('保存中は多重送信されない', async () => {
      let resolveCreate: (value: SourceDocument) => void = () => {}
      mockCreate.mockImplementation(
        () => new Promise(resolve => {
          resolveCreate = resolve
        }),
      )
      const { onSaved } = renderForm()

      await fillRequiredFields()
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))
      expect(screen.getByRole('button', { name: '保存中...' })).toBeDisabled()

      await userEvent.click(screen.getByRole('button', { name: '保存中...' }))
      expect(mockCreate).toHaveBeenCalledTimes(1)

      resolveCreate(SAVED)
      await screen.findByRole('button', { name: '保存する' })
      expect(onSaved).toHaveBeenCalledWith(SAVED)
    })

    it('APIエラー時に入力内容が保持され、再試行できる', async () => {
      mockCreate
        .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
        .mockResolvedValueOnce(SAVED)
      const { onSaved } = renderForm()

      await fillRequiredFields()
      await userEvent.type(screen.getByLabelText(/メモ/), '新聞の社説')
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
      expect(screen.getByLabelText(/タイトル/)).toHaveValue('Le Monde')
      expect(screen.getByLabelText(/本文/)).toHaveValue("Il s'agit d'un article.")
      expect(screen.getByLabelText(/メモ/)).toHaveValue('新聞の社説')

      await userEvent.click(screen.getByRole('button', { name: '保存する' }))
      await screen.findByRole('button', { name: '保存する' })
      expect(onSaved).toHaveBeenCalledWith(SAVED)
      expect(mockCreate).toHaveBeenCalledTimes(2)
    })

    it('Backend 422 を理解可能な文言へ変換する', async () => {
      mockCreate.mockRejectedValueOnce(
        new ApiError(422, {
          detail: [
            { loc: ['body', 'title'], msg: 'String should have at least 1 character' },
          ],
        }),
      )
      renderForm()

      await fillRequiredFields()
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      await screen.findByText('入力内容を確認してください')
      expect(screen.getByText('タイトルを入力してください')).toBeInTheDocument()
      expect(screen.getByLabelText(/タイトル/)).toHaveValue('Le Monde')
    })

    it('保存成功後に onSaved が呼ばれる', async () => {
      mockCreate.mockResolvedValueOnce(SAVED)
      const { onSaved } = renderForm()

      await fillRequiredFields()
      await userEvent.type(screen.getByLabelText(/メモ/), '新聞の社説')
      await userEvent.click(screen.getByRole('button', { name: '保存する' }))

      await screen.findByRole('button', { name: '保存する' })
      expect(onSaved).toHaveBeenCalledWith(SAVED)
    })
  })

  describe('戻る', () => {
    it('一覧に戻るができる', async () => {
      const onBack = vi.fn()
      renderForm({ onBack })

      await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
      expect(onBack).toHaveBeenCalledTimes(1)
    })
  })
})

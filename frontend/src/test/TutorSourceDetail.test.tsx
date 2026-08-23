import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorSourceDetail } from '../components/TutorSourceDetail'
import { ApiError, fetchTutorSource } from '../api/tutor'
import { formatTutorDateTime } from '../utils/tutor'
import type { SourceDocument } from '../types'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSource: vi.fn(),
  }
})

const mockGet = vi.mocked(fetchTutorSource)

const SOURCE: SourceDocument = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  content: "Il s'agit d'un article.\n\nDeuxième paragraphe.",
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  metadata: { note: '新聞の社説' },
}

describe('TutorSourceDetail', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('title / content / note / 保存日時を表示する', async () => {
    mockGet.mockResolvedValueOnce(SOURCE)
    render(
      <TutorSourceDetail sourceId="src-1" onBackToList={() => {}} />,
    )

    await screen.findByRole('heading', { name: 'Le Monde' })
    expect(screen.getByText('新聞の社説')).toBeInTheDocument()
    expect(screen.getByText(formatTutorDateTime(SOURCE.created_at))).toBeInTheDocument()
    const body = document.querySelector('[lang="fr"]')
    expect(body?.textContent).toBe(SOURCE.content)
    expect(body).toHaveStyle({ whiteSpace: 'pre-wrap' })
  })

  it('initialSource がある場合は再取得しない', () => {
    render(
      <TutorSourceDetail
        sourceId="src-1"
        initialSource={SOURCE}
        onBackToList={() => {}}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Le Monde' })).toBeInTheDocument()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('保存直後は確認バナーを出し、続けて追加できる', async () => {
    const onAddAnother = vi.fn()
    render(
      <TutorSourceDetail
        sourceId="src-1"
        initialSource={SOURCE}
        justSaved
        onBackToList={() => {}}
        onAddAnother={onAddAnother}
      />,
    )

    expect(screen.getByText('保存しました')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '続けてテキストを追加' }))
    expect(onAddAnother).toHaveBeenCalledTimes(1)
  })

  it('一覧へ戻れる', async () => {
    const onBackToList = vi.fn()
    render(
      <TutorSourceDetail
        sourceId="src-1"
        initialSource={SOURCE}
        onBackToList={onBackToList}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    expect(onBackToList).toHaveBeenCalledTimes(1)
  })

  it('404 時に Sourceが見つかりません を出す', async () => {
    mockGet.mockRejectedValueOnce(new ApiError(404, { detail: 'missing' }))
    render(
      <TutorSourceDetail sourceId="missing" onBackToList={() => {}} />,
    )

    await screen.findByText('Sourceが見つかりません')
    expect(screen.queryByRole('button', { name: '再試行' })).not.toBeInTheDocument()
  })

  it('通信失敗時は再試行できる', async () => {
    mockGet
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
      .mockResolvedValueOnce(SOURCE)
    render(
      <TutorSourceDetail sourceId="src-1" onBackToList={() => {}} />,
    )

    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    await userEvent.click(screen.getByRole('button', { name: '再試行' }))
    await screen.findByRole('heading', { name: 'Le Monde' })
  })
})

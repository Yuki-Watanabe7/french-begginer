import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorSourceForm } from '../components/TutorSourceForm'
import {
  ApiError,
  ingestTutorAudio,
  ingestTutorConversation,
  ingestTutorPdf,
  ingestTutorSubtitle,
  ingestTutorTextFile,
  ingestTutorUrl,
  ingestTutorYoutube,
} from '../api/tutor'
import type { SourceDocument } from '../types'
import { PDF_MAX_BYTES } from '../utils/sourceIngestion'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    ingestTutorUrl: vi.fn(),
    ingestTutorPdf: vi.fn(),
    ingestTutorYoutube: vi.fn(),
    ingestTutorSubtitle: vi.fn(),
    ingestTutorTextFile: vi.fn(),
    ingestTutorConversation: vi.fn(),
    ingestTutorAudio: vi.fn(),
  }
})

const mockUrl = vi.mocked(ingestTutorUrl)
const mockPdf = vi.mocked(ingestTutorPdf)
const mockYoutube = vi.mocked(ingestTutorYoutube)
const mockSubtitle = vi.mocked(ingestTutorSubtitle)
const mockText = vi.mocked(ingestTutorTextFile)
const mockConversation = vi.mocked(ingestTutorConversation)
const mockAudio = vi.mocked(ingestTutorAudio)

const SAVED: SourceDocument = {
  id: 'src-web',
  source_type: 'web_url',
  title: 'Example',
  content: 'Bonjour.',
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  metadata: {},
}

function fileInput(): HTMLInputElement {
  const input = document.getElementById('tutor-source-file')
  if (!(input instanceof HTMLInputElement)) throw new Error('file input missing')
  return input
}

/** accept で弾かれるファイルでも、change が来たら形式エラーを出せる。 */
function selectFile(file: File) {
  fireEvent.change(fileInput(), { target: { files: [file] } })
}

async function choose(name: string) {
  await userEvent.click(screen.getByRole('radio', { name }))
}

describe('TutorSourceForm ingestion', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('教材の種類を画面幅の中で選べ、手入力を初期表示にする', () => {
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)

    const kinds = screen.getByRole('radiogroup', { name: '教材の種類' })
    expect(kinds).toHaveStyle({ flexWrap: 'wrap', maxWidth: '100%' })
    expect(screen.getByRole('radio', { name: 'テキストを貼り付ける' })).toBeChecked()
    expect(screen.getByText('会話ログ / テキストファイル', { selector: 'span' })).toHaveStyle({
      overflowWrap: 'anywhere',
    })
    expect(screen.getByRole('button', { name: '保存する' })).toBeInTheDocument()
    expect(screen.getByLabelText(/本文/)).toBeInTheDocument()
  })

  it('種類を切り替えても貼り付けた本文を失わない', async () => {
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)

    await userEvent.type(screen.getByLabelText(/タイトル/), 'Le Monde')
    await userEvent.type(screen.getByLabelText(/本文/), 'Bonjour')
    await choose('Web URL')
    expect(screen.queryByLabelText(/本文/)).not.toBeInTheDocument()
    await choose('テキストを貼り付ける')

    expect(screen.getByLabelText(/タイトル/)).toHaveValue('Le Monde')
    expect(screen.getByLabelText(/本文/)).toHaveValue('Bonjour')
  })

  it('URLを取り込み、失敗しても入力を残して技術詳細を出さない', async () => {
    mockUrl
      .mockRejectedValueOnce(new ApiError(400, {
        detail: { code: 'blocked_url', message: 'blocked 10.0.0.1' },
      }))
      .mockResolvedValueOnce(SAVED)
    const onSaved = vi.fn()
    render(<TutorSourceForm onBack={() => {}} onSaved={onSaved} />)

    await choose('Web URL')
    const url = screen.getByRole('textbox', { name: /ページのURL/ })
    expect(url).toHaveStyle({ width: '100%', overflowWrap: 'anywhere' })
    await userEvent.type(url, 'https://secret.example/a')
    await userEvent.type(screen.getByLabelText(/メモ/), '記事')
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))

    expect(await screen.findByText('このURLは安全のため取り込めません')).toBeInTheDocument()
    expect(screen.queryByText(/10\.0\.0\.1/)).not.toBeInTheDocument()
    expect(url).toHaveValue('https://secret.example/a')
    expect(screen.getByLabelText(/メモ/)).toHaveValue('記事')

    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    await screen.findByRole('button', { name: '取り込む' })
    expect(onSaved).toHaveBeenCalledWith(SAVED)
    expect(mockUrl).toHaveBeenCalledTimes(2)
  })

  it('空のURLや http 以外では API を呼ばない', async () => {
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)
    await choose('Web URL')
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(mockUrl).not.toHaveBeenCalled()
    expect(screen.getByText('URLを入力してください')).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox', { name: /ページのURL/ }), 'ftp://example.com')
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(mockUrl).not.toHaveBeenCalled()
    expect(screen.getByText('http または https の URL を入力してください')).toBeInTheDocument()
  })

  it('YouTubeで字幕が無い言語を明示し、URLを残す', async () => {
    mockYoutube.mockRejectedValueOnce(new ApiError(422, {
      detail: {
        code: 'transcript_unavailable',
        message: 'provider payload',
        available_languages: ['en'],
      },
    }))
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)

    await choose('YouTube / 字幕')
    const video = screen.getByRole('textbox', { name: /YouTubeのURL/ })
    await userEvent.type(video, 'https://www.youtube.com/watch?v=abcdefghijk')
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))

    expect(await screen.findByText('指定した言語の字幕がありません（利用できる言語: en）')).toBeInTheDocument()
    expect(screen.queryByText(/provider payload/)).not.toBeInTheDocument()
    expect(video).toHaveValue('https://www.youtube.com/watch?v=abcdefghijk')
    expect(mockYoutube).toHaveBeenCalledWith(expect.objectContaining({
      video: 'https://www.youtube.com/watch?v=abcdefghijk',
      language: 'fr',
    }))
  })

  it('PDF・字幕・テキスト・会話をそれぞれのAPIへ送り、同じファイルを選び直せる', async () => {
    mockPdf.mockResolvedValue({ ...SAVED, source_type: 'pdf' })
    mockSubtitle.mockResolvedValue({ ...SAVED, source_type: 'subtitle' })
    mockText.mockResolvedValue({ ...SAVED, source_type: 'conversation_log' })
    mockConversation.mockResolvedValue({ ...SAVED, source_type: 'conversation_log' })
    const onSaved = vi.fn()
    render(<TutorSourceForm onBack={() => {}} onSaved={onSaved} />)

    await choose('PDF')
    const pdf = new File(['%PDF'], 'lecon.pdf', { type: 'application/pdf' })
    const input = fileInput()
    await userEvent.upload(input, pdf)
    expect(screen.getByText('lecon.pdf')).toHaveStyle({ overflowWrap: 'anywhere' })
    await userEvent.click(input)
    expect(input.value).toBe('')
    await userEvent.upload(input, pdf)
    expect(screen.getByText('lecon.pdf')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    await screen.findByRole('button', { name: '取り込む' })
    expect(mockPdf).toHaveBeenCalledWith(expect.objectContaining({ file: pdf, language: 'fr' }))

    await choose('YouTube / 字幕')
    await choose('字幕ファイル')
    expect(screen.queryByText('lecon.pdf')).not.toBeInTheDocument()
    await userEvent.upload(fileInput(), new File(['1'], 'dialogue.srt', { type: 'application/x-subrip' }))
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    await screen.findByRole('button', { name: '取り込む' })
    expect(mockSubtitle).toHaveBeenCalledTimes(1)

    await choose('会話ログ / テキストファイル')
    expect(screen.getByRole('radio', { name: 'テキストファイル' })).toBeChecked()
    expect(screen.queryByRole('textbox', { name: /JSON/ })).not.toBeInTheDocument()
    await userEvent.upload(fileInput(), new File(['bonjour'], 'note.md', { type: 'text/markdown' }))
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    await screen.findByRole('button', { name: '取り込む' })
    expect(mockText).toHaveBeenCalledTimes(1)

    await choose('会話ログ')
    await userEvent.upload(fileInput(), new File(['{}'], 'dialogue.json', { type: 'application/json' }))
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    await screen.findByRole('button', { name: '取り込む' })
    expect(mockConversation).toHaveBeenCalledTimes(1)
    expect(onSaved).toHaveBeenCalledTimes(4)
  })

  it('形式とサイズのエラーではAPIを呼ばず、選んだファイル名を残す', async () => {
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)
    await choose('PDF')

    selectFile(new File(['abc'], 'notes.txt', { type: 'text/plain' }))
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(mockPdf).not.toHaveBeenCalled()
    expect(screen.getByText('PDF以外のファイルは取り込めません')).toBeInTheDocument()
    expect(screen.getByText('notes.txt')).toBeInTheDocument()

    const big = new File(['x'], 'big.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: PDF_MAX_BYTES + 1 })
    selectFile(big)
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(mockPdf).not.toHaveBeenCalled()
    expect(screen.getByText('PDFのサイズが上限（8MB）を超えています')).toBeInTheDocument()
    expect(screen.getByText('big.pdf')).toBeInTheDocument()
  })

  it('PDFの取り込み失敗でもファイルとメモを残す', async () => {
    mockPdf.mockRejectedValueOnce(new ApiError(422, {
      detail: { code: 'ocr_required', message: 'parser traceback' },
    }))
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)
    await choose('PDF')
    await userEvent.upload(fileInput(), new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    await userEvent.type(screen.getByLabelText(/メモ/), 'スキャン')
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))

    expect(await screen.findByText('文字データが少ないPDFは取り込めません')).toBeInTheDocument()
    expect(screen.queryByText(/traceback/)).not.toBeInTheDocument()
    expect(screen.getByText('scan.pdf')).toBeInTheDocument()
    expect(screen.getByLabelText(/メモ/)).toHaveValue('スキャン')
  })

  it('音声の設定不足と文字起こし失敗を区別し、ファイルを残す', async () => {
    mockAudio
      .mockRejectedValueOnce(new ApiError(503, {
        detail: { code: 'transcription_not_configured', message: 'OPENAI_API_KEY missing' },
      }))
      .mockRejectedValueOnce(new ApiError(502, {
        detail: { code: 'transcription_provider_error', message: 'stack trace' },
      }))
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)
    await choose('音声')
    await userEvent.upload(fileInput(), new File(['audio'], 'memo.m4a', { type: 'audio/mp4' }))

    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(await screen.findByText('文字起こしの設定がありません。管理者に連絡してください')).toBeInTheDocument()
    expect(screen.queryByText(/OPENAI_API_KEY/)).not.toBeInTheDocument()
    expect(screen.getByText('memo.m4a')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))
    expect(await screen.findByText('文字起こしに失敗しました。時間をおいて再度お試しください')).toBeInTheDocument()
    expect(screen.queryByText(/stack trace/)).not.toBeInTheDocument()
    expect(screen.getByText('memo.m4a')).toBeInTheDocument()
  })

  it('取り込み中は同じファイルを二重に送らない', async () => {
    let resolveUpload: (value: SourceDocument) => void = () => {}
    mockPdf.mockImplementation(() => new Promise(resolve => {
      resolveUpload = resolve
    }))
    render(<TutorSourceForm onBack={() => {}} onSaved={() => {}} />)
    await choose('PDF')
    await userEvent.upload(fileInput(), new File(['%PDF'], 'lecon.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: '取り込む' }))

    const pending = screen.getByRole('button', { name: 'PDFを取り込んでいます...' })
    expect(pending).toBeDisabled()
    await userEvent.click(pending)
    expect(mockPdf).toHaveBeenCalledTimes(1)

    resolveUpload({ ...SAVED, source_type: 'pdf' })
    await screen.findByRole('button', { name: '取り込む' })
  })
})

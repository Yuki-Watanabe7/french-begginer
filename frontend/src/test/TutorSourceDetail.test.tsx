import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorSourceDetail } from '../components/TutorSourceDetail'
import {
  ApiError,
  acceptCandidate,
  extractCandidates,
  fetchCandidates,
  fetchSourceLearningSummary,
  fetchTutorSource,
  rejectCandidate,
} from '../api/tutor'
import { formatTutorDateTime } from '../utils/tutor'
import type {
  ExtractCandidatesResponse,
  LearningItemCandidate,
  SourceDocument,
} from '../types'
import {
  EMPTY_SOURCE_LEARNING_SUMMARY,
  sourceLearningSummaryFixture,
} from './sourceLearningSummaryFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSource: vi.fn(),
    fetchSourceLearningSummary: vi.fn(),
    fetchCandidates: vi.fn(),
    extractCandidates: vi.fn(),
    acceptCandidate: vi.fn(),
    rejectCandidate: vi.fn(),
  }
})

const mockGet = vi.mocked(fetchTutorSource)
const mockSummary = vi.mocked(fetchSourceLearningSummary)
const mockFetchCandidates = vi.mocked(fetchCandidates)
const mockExtract = vi.mocked(extractCandidates)
const mockAccept = vi.mocked(acceptCandidate)
const mockReject = vi.mocked(rejectCandidate)

const SOURCE: SourceDocument = {
  id: 'src-1',
  source_type: 'manual_text',
  title: 'Le Monde',
  content: "Il s'agit d'un article.\n\nDeuxième paragraphe.",
  language: 'fr',
  created_at: '2026-08-23T12:00:00+00:00',
  metadata: { note: '新聞の社説' },
}

function candidate(
  overrides: Partial<LearningItemCandidate> = {},
): LearningItemCandidate {
  return {
    id: 'cand-1',
    source_document_id: 'src-1',
    item_type: 'expression',
    canonical_form: 'se rendre compte',
    meaning_ja: '〜に気づく',
    explanation_ja: 'よく使う表現',
    level: 'A2',
    evidence_span: { start: 10, end: 22 },
    evidence_text: 'rendu compte',
    confidence: 0.9,
    status: 'candidate',
    extraction_version: 'extract-v1',
    created_at: '2026-08-24T12:00:00+00:00',
    ...overrides,
  }
}

const ITEM = {
  id: 'item-1',
  item_type: 'expression' as const,
  canonical_form: 'se rendre compte',
  meaning_ja: '〜に気づく',
  explanation_ja: 'よく使う表現',
  level: 'A2' as const,
  source_refs: [],
  status: 'active',
  created_at: '2026-08-24T12:00:00+00:00',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    void rej
  })
  return { promise, resolve }
}

function renderDetail() {
  render(
    <TutorSourceDetail
      sourceId="src-1"
      initialSource={SOURCE}
      onBackToList={() => {}}
    />,
  )
}

describe('TutorSourceDetail', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchCandidates.mockResolvedValue([])
    mockSummary.mockResolvedValue(EMPTY_SOURCE_LEARNING_SUMMARY)
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

  it('PDFの出典と候補のページを表示し、内部情報は出さない', async () => {
    const pdf: SourceDocument = {
      id: 'src-pdf',
      source_type: 'pdf',
      title: 'Leçon',
      content: 'Bonjour.\n\nAu revoir.',
      language: 'fr',
      created_at: '2026-08-23T12:00:00+00:00',
      metadata: {
        page_count: 2,
        file_sha256: 'sha256:file',
        parser_name: 'pypdf',
        note: '授業',
      },
      content_hash: 'sha256:content',
      ingestion_version: 'source-ingest-v1',
      provenance: {
        filename: 'lecon.pdf',
        canonical_locator: 'sha256:locator',
        original_content_hash: 'sha256:raw',
        adapter_version: 'pdf-text-v1',
        provider: 'secret-provider',
        ingestion_version: 'source-ingest-v1',
        ingested_at: '2026-08-23T12:00:00+00:00',
      },
      segments: [
        { normalized_start: 0, normalized_end: 8, page_number: 1 },
        { normalized_start: 10, normalized_end: 20, page_number: 2 },
      ],
    }
    mockFetchCandidates.mockResolvedValue([
      candidate({
        evidence_span: { start: 10, end: 20 },
        evidence_text: 'Au revoir.',
      }),
    ])
    render(
      <TutorSourceDetail sourceId="src-pdf" initialSource={pdf} onBackToList={() => {}} />,
    )

    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('lecon.pdf')).toHaveStyle({ overflowWrap: 'anywhere' })
    expect(screen.getByText('ページ数')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1ページ')).toBeInTheDocument()
    expect(screen.getAllByText('2ページ').length).toBeGreaterThan(0)
    expect(screen.getByText('授業')).toBeInTheDocument()
    expect(screen.getAllByText('Au revoir.').length).toBeGreaterThan(0)
    expect(screen.queryByText(/sha256/)).not.toBeInTheDocument()
    expect(screen.queryByText(/secret-provider/)).not.toBeInTheDocument()
    expect(screen.queryByText(/pypdf/)).not.toBeInTheDocument()
    expect(screen.queryByText('source-ingest-v1')).not.toBeInTheDocument()
    expect(screen.queryByText('pdf-text-v1')).not.toBeInTheDocument()
    await screen.findByRole('button', { name: '学習候補を抽出' })
  })

  it('YouTubeのURLと字幕の言語を表示し、providerは出さない', async () => {
    const url = 'https://www.youtube.com/watch?v=abcdefghijk'
    const video: SourceDocument = {
      id: 'src-video',
      source_type: 'youtube_transcript',
      title: 'Dialogue',
      content: 'Bonjour tout le monde.',
      language: 'fr',
      created_at: '2026-08-23T12:00:00+00:00',
      metadata: {
        original_url: url,
        transcript_language: 'fr',
        provider: 'youtube-transcript-api',
        provider_version: '1.2.3',
      },
      provenance: {
        canonical_locator: url,
        provider: 'youtube-transcript-api',
        provider_model: 'captions',
        ingested_at: '2026-08-23T12:00:00+00:00',
      },
    }
    render(
      <TutorSourceDetail sourceId="src-video" initialSource={video} onBackToList={() => {}} />,
    )

    const link = screen.getByRole('link', { name: url })
    expect(link).toHaveAttribute('href', url)
    expect(link).toHaveStyle({ overflowWrap: 'anywhere' })
    expect(screen.getByText('YouTube')).toBeInTheDocument()
    expect(screen.getByText('字幕の言語')).toBeInTheDocument()
    expect(screen.getByText('fr')).toBeInTheDocument()
    expect(screen.queryByText('youtube-transcript-api')).not.toBeInTheDocument()
    expect(screen.queryByText('captions')).not.toBeInTheDocument()
    expect(screen.queryByText('1.2.3')).not.toBeInTheDocument()
    await screen.findByRole('button', { name: '学習候補を抽出' })
  })

  it('initialSource がある場合は再取得しない', async () => {
    renderDetail()

    expect(screen.getByRole('heading', { name: 'Le Monde' })).toBeInTheDocument()
    expect(mockGet).not.toHaveBeenCalled()
    await screen.findByRole('button', { name: '学習候補を抽出' })
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
    await userEvent.click(screen.getByRole('button', { name: '続けて教材を追加' }))
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

  it('学習する でこの Source の練習を開始できる', async () => {
    const onStartPractice = vi.fn()
    render(
      <TutorSourceDetail
        sourceId="src-1"
        initialSource={SOURCE}
        onBackToList={() => {}}
        onStartPractice={onStartPractice}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '学習する' }))
    expect(onStartPractice).toHaveBeenCalledTimes(1)
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

describe('TutorSourceDetail の学習候補', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchCandidates.mockResolvedValue([])
    mockSummary.mockResolvedValue(EMPTY_SOURCE_LEARNING_SUMMARY)
  })

  it('抽出ボタンと empty state を表示する', async () => {
    renderDetail()

    await screen.findByRole('button', { name: '学習候補を抽出' })
    expect(
      screen.getByText('まだ学習候補がありません。抽出すると、覚える候補を確認できます'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/metadata/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/openai/i)).not.toBeInTheDocument()
  })

  it('抽出中は多重実行せず、完了後に候補を表示する', async () => {
    const pending = deferred<ExtractCandidatesResponse>()
    mockExtract.mockReturnValueOnce(pending.promise)
    mockFetchCandidates
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([candidate()])

    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '学習候補を抽出' }))
    expect(screen.getByRole('button', { name: '抽出しています...' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '抽出しています...' }))
    expect(mockExtract).toHaveBeenCalledTimes(1)

    pending.resolve({
      source_document_id: 'src-1',
      extraction_version: 'extract-v1',
      created: [candidate()],
      skipped: [],
    })
    await screen.findByText('se rendre compte')
    expect(screen.getByText('1件の新しい候補を抽出しました')).toBeInTheDocument()
    expect(screen.getByText('表現')).toBeInTheDocument()
    expect(screen.getByText('〜に気づく')).toBeInTheDocument()
    expect(screen.getByText('よく使う表現')).toBeInTheDocument()
    expect(screen.getByText('rendu compte')).toBeInTheDocument()
    expect(screen.getByText('A2')).toBeInTheDocument()
    expect(screen.getByText('確信度 90%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'もう一度抽出する' })).toBeInTheDocument()
  })

  it('vocabulary / expression / grammar / conjugation を表示する', async () => {
    mockFetchCandidates.mockResolvedValue([
      candidate({ id: 'v', item_type: 'vocabulary', canonical_form: 'stratégie' }),
      candidate({ id: 'e', item_type: 'expression', canonical_form: 'se rendre compte' }),
      candidate({ id: 'g', item_type: 'grammar', canonical_form: 'il fallait' }),
      candidate({ id: 'c', item_type: 'conjugation', canonical_form: 'changer' }),
    ])
    renderDetail()

    await screen.findByText('語彙')
    expect(screen.getByText('表現')).toBeInTheDocument()
    expect(screen.getByText('文法')).toBeInTheDocument()
    expect(screen.getByText('活用')).toBeInTheDocument()
    expect(screen.getByText('stratégie')).toBeInTheDocument()
    expect(screen.getByText('il fallait')).toBeInTheDocument()
    expect(screen.getByText('changer')).toBeInTheDocument()
  })

  it('採用成功後に status が分かり、失敗時は未確認のまま残る', async () => {
    mockFetchCandidates.mockResolvedValue([candidate()])
    mockAccept.mockRejectedValueOnce(
      new ApiError(500, { detail: 'boom' }),
    )
    renderDetail()

    await userEvent.click(await screen.findByRole('button', { name: '採用する' }))
    await screen.findByText('サーバーでエラーが発生しました。時間をおいて再度お試しください')
    expect(screen.getByText('未確認')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '採用する' })).toBeInTheDocument()

    mockAccept.mockResolvedValueOnce({
      candidate: candidate({ status: 'accepted' }),
      item: ITEM,
      merged: true,
    })
    await userEvent.click(screen.getByRole('button', { name: '採用する' }))
    await screen.findByText('採用済み')
    expect(screen.queryByRole('button', { name: '採用する' })).not.toBeInTheDocument()
  })

  it('却下成功後も一覧に残り、フィルタで隠せる', async () => {
    mockFetchCandidates.mockResolvedValue([candidate()])
    mockReject.mockResolvedValue(candidate({ status: 'rejected' }))
    renderDetail()

    await userEvent.click(await screen.findByRole('button', { name: '却下する' }))
    await screen.findByText('却下')
    expect(screen.getByText('se rendre compte')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: /未確認/ }))
    expect(screen.getByText('この条件の候補はありません')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /却下/ }))
    expect(screen.getByText('se rendre compte')).toBeInTheDocument()
  })

  it('既存の採用済み・却下を表示し、再抽出しても消さない', async () => {
    const accepted = candidate({ id: 'a', status: 'accepted', canonical_form: 'kept' })
    const rejected = candidate({ id: 'r', status: 'rejected', canonical_form: 'dropped' })
    mockFetchCandidates
      .mockResolvedValueOnce([accepted, rejected])
      .mockResolvedValueOnce([accepted, rejected])
    mockExtract.mockResolvedValue({
      source_document_id: 'src-1',
      extraction_version: 'extract-v1',
      created: [],
      skipped: [accepted, rejected],
    })
    renderDetail()

    await screen.findByText('kept')
    expect(screen.getByText('dropped')).toBeInTheDocument()
    expect(screen.getAllByText('採用済み').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '採用する' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'もう一度抽出する' }))
    await screen.findByText('新しい候補はありません。既存の候補を表示しています')
    expect(screen.getByText('kept')).toBeInTheDocument()
    expect(screen.getByText('dropped')).toBeInTheDocument()
  })

  it('抽出失敗時は既存候補を残し、ユーザー向け文言を出す', async () => {
    mockFetchCandidates.mockResolvedValue([candidate()])
    mockExtract.mockRejectedValue(
      new ApiError(503, { detail: 'OPENAI_API_KEY が設定されていない' }),
    )
    renderDetail()

    await screen.findByText('se rendre compte')
    await userEvent.click(screen.getByRole('button', { name: 'もう一度抽出する' }))
    await screen.findByText(
      '学習候補の抽出に必要な設定がありません。管理者に連絡してください',
    )
    expect(screen.getByText('se rendre compte')).toBeInTheDocument()
    expect(screen.getByText('未確認')).toBeInTheDocument()
  })

  it('抽出 0 件の empty state を出す', async () => {
    mockExtract.mockResolvedValue({
      source_document_id: 'src-1',
      extraction_version: 'extract-v1',
      created: [],
      skipped: [],
    })
    renderDetail()

    await userEvent.click(await screen.findByRole('button', { name: '学習候補を抽出' }))
    await screen.findByText('学習候補は見つかりませんでした')
    expect(screen.getByRole('button', { name: 'もう一度抽出する' })).toBeInTheDocument()
  })
})

describe('TutorSourceDetail の学習状況', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockFetchCandidates.mockResolvedValue([])
    mockSummary.mockResolvedValue(EMPTY_SOURCE_LEARNING_SUMMARY)
  })

  it('採用前は empty を出し、候補のページ導線は残す', async () => {
    const pdf: SourceDocument = {
      id: 'src-pdf',
      source_type: 'pdf',
      title: 'Leçon',
      content: 'Bonjour.\n\nAu revoir.',
      language: 'fr',
      created_at: '2026-08-23T12:00:00+00:00',
      metadata: { page_count: 2 },
      segments: [
        { normalized_start: 0, normalized_end: 8, page_number: 1 },
        { normalized_start: 10, normalized_end: 20, page_number: 2 },
      ],
    }
    mockFetchCandidates.mockResolvedValue([
      candidate({
        evidence_span: { start: 10, end: 20 },
        evidence_text: 'Au revoir.',
      }),
    ])
    render(
      <TutorSourceDetail sourceId="src-pdf" initialSource={pdf} onBackToList={() => {}} />,
    )

    expect(await screen.findByText('採用した学習項目はまだありません')).toBeInTheDocument()
    expect(screen.getAllByText('2ページ').length).toBeGreaterThan(0)
    expect(screen.queryByText('source-learning-summary-v1')).not.toBeInTheDocument()
    expect(screen.queryByText('related_item_current_state')).not.toBeInTheDocument()
    const section = screen.getByRole('region', { name: '学習状況' })
    expect(section).toHaveStyle({ width: '100%', maxWidth: '100%', overflowWrap: 'anywhere' })
  })

  it('読み込み中と取得失敗からの再読み込みを扱う', async () => {
    const pending = deferred<ReturnType<typeof sourceLearningSummaryFixture>>()
    mockSummary.mockReturnValueOnce(pending.promise)
    renderDetail()

    expect(screen.getByText('学習状況を読み込み中...')).toBeInTheDocument()
    pending.resolve(EMPTY_SOURCE_LEARNING_SUMMARY)
    await screen.findByText('採用した学習項目はまだありません')

    mockSummary.mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }))
    renderDetail()
    await screen.findByText('学習状況を取得できませんでした。時間をおいて再度お試しください')
    const retry = screen.getByRole('button', { name: '学習状況を再読み込み' })
    expect(retry).toHaveStyle({ width: '100%', minHeight: '48px' })
    mockSummary.mockResolvedValueOnce(
      sourceLearningSummaryFixture({
        accepted_item_count: 12,
        started_item_count: 7,
        due_direction_count: 3,
        mastered_or_known_count: 2,
        attempts: 4,
        correct_count: 3,
        correct_rate: 0.75,
        recognition: {
          skill_direction: 'recognition',
          attempt_count: 4,
          correct_count: 3,
          correct_rate: 0.75,
          due_count: 1,
        },
        production: {
          skill_direction: 'production',
          attempt_count: 3,
          correct_count: 1,
          correct_rate: 1 / 3,
          due_count: 2,
        },
      }),
    )
    await userEvent.click(retry)
    expect(await screen.findByTestId('source-learning-accepted')).toHaveTextContent(
      '採用した項目 12',
    )
  })

  it('関連項目の現在状態と direction の差を出す', async () => {
    mockSummary.mockResolvedValue(
      sourceLearningSummaryFixture({
        accepted_item_count: 12,
        started_item_count: 7,
        due_direction_count: 3,
        mastered_or_known_count: 2,
        attempts: 4,
        correct_count: 3,
        correct_rate: 0.75,
        recognition: {
          skill_direction: 'recognition',
          attempt_count: 4,
          correct_count: 3,
          correct_rate: 0.75,
          due_count: 1,
        },
        production: {
          skill_direction: 'production',
          attempt_count: 3,
          correct_count: 1,
          correct_rate: 1 / 3,
          due_count: 2,
        },
      }),
    )
    renderDetail()

    expect(await screen.findByTestId('source-learning-accepted')).toHaveTextContent(
      '採用した項目 12',
    )
    expect(screen.getByTestId('source-learning-started')).toHaveTextContent('学習開始済み 7')
    expect(screen.getByTestId('source-learning-due')).toHaveTextContent('復習待ち 3')
    expect(screen.getByTestId('source-learning-known')).toHaveTextContent('既知/十分定着 2')
    expect(screen.getByText('見て分かる 3/4')).toBeInTheDocument()
    expect(screen.getByText('自分で言う 1/3')).toBeInTheDocument()
    expect(screen.getByText('正答 3/4')).toBeInTheDocument()
    expect(screen.getByText('この教材に結びついた項目の、いまの状態です。')).toHaveStyle({
      overflowWrap: 'anywhere',
    })
    expect(screen.queryByText('related_item_current_state')).not.toBeInTheDocument()
  })
})

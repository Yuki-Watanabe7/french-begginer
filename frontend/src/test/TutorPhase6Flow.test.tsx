import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorFlow } from '../components/TutorFlow'
import {
  acceptCandidate,
  createTodaySession,
  extractCandidates,
  fetchCandidates,
  fetchReviewQueue,
  fetchTutorSources,
  fetchTodayPlan,
  fetchTutorItem,
  fetchTutorItems,
  ingestTutorPdf,
  ingestTutorUrl,
  submitExerciseAnswer,
} from '../api/tutor'
import type {
  LearningItem,
  LearningItemCandidate,
  SourceDocument,
} from '../types'
import { EMPTY_REVIEW_QUEUE } from './reviewQueueFixtures'
import {
  EMPTY_TODAY_PLAN,
  todayPlanEntryFixture,
  todayPlanFixture,
  todaySessionFixture,
} from './todayPlanFixtures'

vi.mock('../api/tutor', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/tutor')>()
  return {
    ...actual,
    fetchTutorSources: vi.fn(),
    fetchTutorSource: vi.fn(),
    createTutorSource: vi.fn(),
    fetchCandidates: vi.fn(),
    extractCandidates: vi.fn(),
    acceptCandidate: vi.fn(),
    ingestTutorUrl: vi.fn(),
    ingestTutorPdf: vi.fn(),
    fetchReviewQueue: vi.fn(),
    fetchTodayPlan: vi.fn(),
    createTodaySession: vi.fn(),
    fetchTutorItems: vi.fn(),
    fetchTutorItem: vi.fn(),
    submitExerciseAnswer: vi.fn(),
  }
})

const mockList = vi.mocked(fetchTutorSources)
const mockCandidates = vi.mocked(fetchCandidates)
const mockExtract = vi.mocked(extractCandidates)
const mockAccept = vi.mocked(acceptCandidate)
const mockIngestUrl = vi.mocked(ingestTutorUrl)
const mockIngestPdf = vi.mocked(ingestTutorPdf)
const mockQueue = vi.mocked(fetchReviewQueue)
const mockPlan = vi.mocked(fetchTodayPlan)
const mockToday = vi.mocked(createTodaySession)
const mockItems = vi.mocked(fetchTutorItems)
const mockItem = vi.mocked(fetchTutorItem)
const mockSubmit = vi.mocked(submitExerciseAnswer)

const WEB_CONTENT = 'La bibliothèque ouvre à neuf heures.'
const WEB: SourceDocument = {
  id: 'src-web',
  source_type: 'web_url',
  title: 'Bibliothèque',
  content: WEB_CONTENT,
  language: 'fr',
  created_at: '2026-10-12T00:00:00+00:00',
  metadata: {
    final_url: 'https://example.com/articles/bibliotheque',
  },
  provenance: {
    canonical_locator: 'https://example.com/articles/bibliotheque',
    mime_type: 'text/html',
  },
  segments: [
    { normalized_start: 0, normalized_end: WEB_CONTENT.length },
  ],
}

const PAGE_1 = 'Le café est prêt.'
const PAGE_2 = 'À demain.'
const PDF_CONTENT = `${PAGE_1}\n\n${PAGE_2}`
const PDF: SourceDocument = {
  id: 'src-pdf',
  source_type: 'pdf',
  title: 'Leçon',
  content: PDF_CONTENT,
  language: 'fr',
  created_at: '2026-10-12T00:00:00+00:00',
  metadata: { page_count: 2 },
  provenance: { filename: 'lecon.pdf' },
  segments: [
    { normalized_start: 0, normalized_end: PAGE_1.length, page_number: 1 },
    {
      normalized_start: PAGE_1.length + 2,
      normalized_end: PDF_CONTENT.length,
      page_number: 2,
    },
  ],
}

const CANDIDATE: LearningItemCandidate = {
  id: 'cand-1',
  source_document_id: WEB.id,
  item_type: 'vocabulary',
  canonical_form: 'bibliothèque',
  meaning_ja: '図書館',
  explanation_ja: null,
  level: 'A2',
  evidence_span: { start: 3, end: 3 + 'bibliothèque'.length },
  evidence_text: 'bibliothèque',
  confidence: 0.9,
  status: 'candidate',
  extraction_version: 'extract-v1',
  created_at: '2026-10-12T00:00:00+00:00',
}

const ITEM: LearningItem = {
  id: 'item-biblio',
  item_type: 'vocabulary',
  canonical_form: 'bibliothèque',
  meaning_ja: '図書館',
  explanation_ja: null,
  level: 'A2',
  source_refs: [],
  created_at: '2026-10-12T00:00:00+00:00',
  status: 'active',
}

function renderFlow() {
  render(<TutorFlow onBack={() => {}} />)
}

describe('Tutor Phase 6 external source flow', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockList.mockResolvedValue([])
    mockCandidates.mockResolvedValue([])
    mockQueue.mockResolvedValue(EMPTY_REVIEW_QUEUE)
    mockPlan.mockResolvedValue(EMPTY_TODAY_PLAN)
    mockItems.mockResolvedValue([ITEM])
    mockItem.mockResolvedValue(ITEM)
  })

  it('URLの取り込みから候補の採用を経て今日の学習で解ける', async () => {
    const user = userEvent.setup()
    let accepted = false
    mockIngestUrl.mockResolvedValue(WEB)
    mockExtract.mockImplementation(async () => {
      mockCandidates.mockResolvedValue([CANDIDATE])
      return {
        source_document_id: WEB.id,
        extraction_version: 'extract-v1',
        created: [CANDIDATE],
        skipped: [],
      }
    })
    mockAccept.mockResolvedValue({
      candidate: { ...CANDIDATE, status: 'accepted' },
      item: ITEM,
      merged: false,
    })
    mockPlan.mockImplementation(async () =>
      accepted
        ? todayPlanFixture({
            new_count: 1,
            entries: [
              todayPlanEntryFixture({
                learning_item_id: ITEM.id,
                canonical_form: 'bibliothèque',
                meaning_ja: '図書館',
                activity_kind: 'new_practice',
                skill_direction: 'recognition',
                selected_exercise_type: 'meaning_recognition',
                reason_codes: ['RECENT_SOURCE'],
                explanation: '最近追加した教材に出てきた表現です',
                source_titles: ['Bibliothèque'],
              }),
            ],
            summary_reason_codes: ['RECENT_SOURCE'],
          })
        : EMPTY_TODAY_PLAN,
    )
    mockToday.mockResolvedValue(
      todaySessionFixture(
        [
          {
            learning_item_id: ITEM.id,
            exercise_type: 'meaning_recognition',
            skill_direction: 'recognition',
            prompt: '次のフランス語の意味を選んでください。\n\nbibliothèque',
            response_kind: 'choice',
            options: ['図書館', '駅'],
            source_context: null,
            exercise_version: 'exercise-v1',
          },
        ],
        [
          todayPlanEntryFixture({
            learning_item_id: ITEM.id,
            canonical_form: 'bibliothèque',
            activity_kind: 'new_practice',
            skill_direction: 'recognition',
            selected_exercise_type: 'meaning_recognition',
            reason_codes: ['RECENT_SOURCE'],
          }),
        ],
      ),
    )
    mockSubmit.mockResolvedValue({
      correct: true,
      correct_answer: '図書館',
      given: '図書館',
      explanation_ja: null,
      source_context: null,
      meaning_ja: '図書館',
      canonical_form: 'bibliothèque',
    })

    renderFlow()
    await user.click(await screen.findByRole('button', { name: '教材を追加' }))
    await user.click(screen.getByRole('radio', { name: 'Web URL' }))
    await user.type(
      screen.getByRole('textbox', { name: /ページのURL/ }),
      'https://example.com/articles/bibliotheque',
    )
    await user.click(screen.getByRole('button', { name: '取り込む' }))

    await screen.findByText('取り込みました')
    expect(screen.getByRole('heading', { name: 'Bibliothèque' })).toBeInTheDocument()
    expect(screen.getByText('Web')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'https://example.com/articles/bibliotheque' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('text/html')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '学習候補を抽出' }))
    expect(await screen.findByRole('article', { name: /bibliothèque/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '採用する' }))
    expect(await screen.findByText('採用済み')).toBeInTheDocument()
    accepted = true

    await user.click(screen.getByRole('button', { name: '一覧に戻る' }))
    expect(await screen.findByText('bibliothèque')).toBeInTheDocument()
    expect(screen.getByText('新しい項目')).toBeInTheDocument()
    expect(screen.getAllByText('最近追加した教材に出てきた表現です').length).toBeGreaterThan(0)
    expect(screen.queryByText('出題数を選択')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '学習を始める' }))
    expect(mockToday).toHaveBeenCalledWith({})
    expect(screen.queryByText('出題数を選択')).not.toBeInTheDocument()
    const choice = screen.getByRole('button', { name: '図書館' })
    expect(choice).toHaveStyle({ width: '100%', minHeight: '48px' })
    await user.click(choice)
    expect(await screen.findByText('✓ 正解')).toBeInTheDocument()
  })

  it('PDFの取り込み中を示し、詳細でページと候補の位置を出す', async () => {
    const user = userEvent.setup()
    let resolvePdf: (document: SourceDocument) => void = () => {}
    mockIngestPdf.mockImplementation(
      () =>
        new Promise(resolve => {
          resolvePdf = resolve
        }),
    )
    const cafeStart = PDF_CONTENT.indexOf('café')
    const pdfCandidate: LearningItemCandidate = {
      ...CANDIDATE,
      id: 'cand-pdf',
      source_document_id: PDF.id,
      canonical_form: 'café',
      meaning_ja: 'コーヒー',
      evidence_span: { start: cafeStart, end: cafeStart + 'café'.length },
      evidence_text: 'café',
    }
    mockExtract.mockImplementation(async () => {
      mockCandidates.mockResolvedValue([pdfCandidate])
      return {
        source_document_id: PDF.id,
        extraction_version: 'extract-v1',
        created: [pdfCandidate],
        skipped: [],
      }
    })

    renderFlow()
    await user.click(await screen.findByRole('button', { name: '教材を追加' }))
    await user.click(screen.getByRole('radio', { name: 'PDF' }))
    const file = new File(['%PDF'], 'lecon.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText(/^ファイル/), file)
    expect(screen.getByText('lecon.pdf')).toHaveStyle({ overflowWrap: 'anywhere' })
    await user.click(screen.getByRole('button', { name: '取り込む' }))

    expect(await screen.findByRole('button', { name: 'PDFを取り込んでいます...' })).toBeDisabled()
    expect(screen.getByText('lecon.pdf')).toBeInTheDocument()
    resolvePdf(PDF)

    await screen.findByText('取り込みました')
    expect(screen.getByRole('heading', { name: 'Leçon' })).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('lecon.pdf')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1ページ')).toBeInTheDocument()
    expect(screen.getByText('2ページ')).toBeInTheDocument()
    expect(screen.queryByText('sha256')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '学習候補を抽出' }))
    expect(await screen.findByRole('article', { name: /café/ })).toBeInTheDocument()
    expect(screen.getAllByText('1ページ').length).toBeGreaterThan(1)
  })

  it('狭い幅でも形式選択、URL、ファイル、取り込みボタンが収まる', async () => {
    const user = userEvent.setup()
    renderFlow()
    await user.click(await screen.findByRole('button', { name: '教材を追加' }))

    expect(screen.getByRole('radio', { name: 'テキストを貼り付ける' })).toBeChecked()
    const kinds = screen.getByRole('radiogroup', { name: '教材の種類' })
    expect(kinds).toHaveStyle({ flexWrap: 'wrap', maxWidth: '100%' })
    expect(screen.getByText('会話ログ / テキストファイル', { selector: 'span' })).toHaveStyle({
      overflowWrap: 'anywhere',
    })

    await user.click(screen.getByRole('radio', { name: 'Web URL' }))
    const url = screen.getByRole('textbox', { name: /ページのURL/ })
    expect(url).toHaveStyle({
      width: '100%',
      maxWidth: '100%',
      minHeight: '72px',
      overflowWrap: 'anywhere',
    })
    await user.type(url, 'https://example.com/' + 'bibliotheque/'.repeat(8))
    expect(url).toHaveValue('https://example.com/' + 'bibliotheque/'.repeat(8))

    await user.click(screen.getByRole('radio', { name: 'PDF' }))
    const longName = 'lecon-tres-longue-pour-un-petit-ecran.pdf'
    await user.upload(
      screen.getByLabelText(/^ファイル/),
      new File(['%PDF'], longName, { type: 'application/pdf' }),
    )
    expect(screen.getByText(longName)).toHaveStyle({ overflowWrap: 'anywhere' })
    expect(screen.getByRole('button', { name: '取り込む' })).toHaveStyle({
      width: '100%',
      minHeight: '48px',
    })
  })
})

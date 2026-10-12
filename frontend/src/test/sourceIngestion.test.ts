import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/tutor'
import type { SourceDocument, SourceSegment } from '../types'
import { formatTutorDateTime } from '../utils/tutor'
import {
  AUDIO_MAX_BYTES,
  evidenceProvenanceLabel,
  INGEST_FILE_SPECS,
  PDF_MAX_BYTES,
  sourceContentBlocks,
  sourceProvenanceFacts,
  sourceTypeLabel,
  tutorIngestErrorMessage,
  validateHttpUrl,
  validateIngestFile,
} from '../utils/sourceIngestion'

const PDF: SourceDocument = {
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
  },
  content_hash: 'sha256:content',
  ingestion_version: 'source-ingest-v1',
  provenance: {
    filename: '../../lecon.pdf',
    canonical_locator: 'sha256:locator',
    provider: 'secret-provider',
    adapter_version: 'pdf-text-v1',
    original_content_hash: 'sha256:raw',
  },
  segments: [
    { normalized_start: 0, normalized_end: 8, page_number: 1 },
    { normalized_start: 10, normalized_end: 20, page_number: 2 },
  ],
}

describe('sourceTypeLabel', () => {
  it('一覧に出せる短い名前へ変換し、未知の内部名は出さない', () => {
    expect(sourceTypeLabel('web_url')).toBe('Web')
    expect(sourceTypeLabel('youtube_transcript')).toBe('YouTube')
    expect(sourceTypeLabel('audio_transcript')).toBe('音声')
    expect(sourceTypeLabel('future_connector')).toBe('教材')
  })

  it('テキストファイルと会話ログを source_format で分ける', () => {
    expect(sourceTypeLabel('conversation_log', { source_format: 'markdown' })).toBe('テキスト')
    expect(sourceTypeLabel('conversation_log', { source_format: 'conversation_json' })).toBe('会話')
    expect(sourceTypeLabel('conversation_log')).toBe('会話')
  })
})

describe('sourceProvenanceFacts', () => {
  it('ファイル名とページ数だけを出し、hash と provider は落とす', () => {
    expect(sourceProvenanceFacts(PDF)).toEqual([
      { label: 'ファイル', value: 'lecon.pdf' },
      { label: 'ページ数', value: '2' },
    ])
  })

  it('Web は最終URLを優先し、元のURLが違うときだけ併記する', () => {
    const source: SourceDocument = {
      ...PDF,
      source_type: 'web_url',
      metadata: {
        requested_url: 'https://example.com/start',
        final_url: 'https://example.com/article',
        file_sha256: 'sha256:nope',
      },
      provenance: { canonical_locator: 'https://example.com/start' },
    }
    expect(sourceProvenanceFacts(source)).toEqual([
      { label: 'URL', value: 'https://example.com/article', href: 'https://example.com/article' },
      { label: '元のURL', value: 'https://example.com/start', href: 'https://example.com/start' },
    ])
  })

  it('sha256 の locator は URL として表示しない', () => {
    const source: SourceDocument = {
      ...PDF,
      source_type: 'web_url',
      metadata: {},
      provenance: { canonical_locator: 'sha256:abc' },
    }
    expect(sourceProvenanceFacts(source)).toEqual([])
  })
})

describe('page and time provenance', () => {
  it('本文をページごとに区切り、範囲が壊れていたら全文のままにする', () => {
    expect(sourceContentBlocks(PDF)).toEqual([
      { text: 'Bonjour.', label: '1ページ' },
      { text: 'Au revoir.', label: '2ページ' },
    ])
    expect(sourceContentBlocks({
      content: PDF.content,
      segments: [{ normalized_start: 0, normalized_end: 3, page_number: 1 }],
    })).toBeNull()
  })

  it('時刻と話者を人間向けにし、候補の根拠位置へ戻す', () => {
    const segments: SourceSegment[] = [
      {
        normalized_start: 0,
        normalized_end: 5,
        speaker: 'Marie',
        timestamp: '2026-04-01T03:00:00Z',
      },
      {
        normalized_start: 7,
        normalized_end: 12,
        start_seconds: 65,
        end_seconds: 72,
        page_number: 3,
      },
    ]
    expect(evidenceProvenanceLabel(segments, { start: 0, end: 5 })).toBe(
      `Marie · ${formatTutorDateTime('2026-04-01T03:00:00Z')}`,
    )
    expect(evidenceProvenanceLabel(segments, { start: 7, end: 12 })).toBe('1:05–1:12 · 3ページ')
    expect(evidenceProvenanceLabel(segments, { start: 0, end: 12 })).toBe(
      'Marie · 1:05–1:12 · 3ページ',
    )
  })

  it('連続するページは範囲でまとめる', () => {
    const segments: SourceSegment[] = [
      { normalized_start: 0, normalized_end: 2, page_number: 2 },
      { normalized_start: 4, normalized_end: 6, page_number: 3 },
      { normalized_start: 8, normalized_end: 10, page_number: 4 },
    ]
    expect(evidenceProvenanceLabel(segments, { start: 0, end: 10 })).toBe('2–4ページ')
  })
})

describe('ingest validation and errors', () => {
  it('URL は http と https だけを受ける', () => {
    expect(validateHttpUrl('  ')).toBe('URLを入力してください')
    expect(validateHttpUrl('ftp://example.com')).toBe('http または https の URL を入力してください')
    expect(validateHttpUrl('https://example.com/a')).toBeNull()
  })

  it('拡張子・空ファイル・サイズを形式ごとに分ける', () => {
    expect(validateIngestFile({ name: 'notes.txt', size: 10 }, INGEST_FILE_SPECS.pdf)).toBe(
      'PDF以外のファイルは取り込めません',
    )
    expect(validateIngestFile({ name: 'empty.pdf', size: 0 }, INGEST_FILE_SPECS.pdf)).toBe(
      'ファイルが空です',
    )
    expect(validateIngestFile(
      { name: 'big.pdf', size: PDF_MAX_BYTES + 1 },
      INGEST_FILE_SPECS.pdf,
    )).toBe('PDFのサイズが上限（8MB）を超えています')
    expect(validateIngestFile({ name: 'voice.m4a', size: 20 }, INGEST_FILE_SPECS.audio)).toBeNull()
    expect(validateIngestFile(
      { name: 'voice.m4a', size: AUDIO_MAX_BYTES + 1 },
      INGEST_FILE_SPECS.audio,
    )).toMatch(/25MB/)
    expect(validateIngestFile({ name: 'talk.json', size: 20 }, INGEST_FILE_SPECS.conversation)).toBeNull()
    expect(validateIngestFile({ name: 'talk.txt', size: 20 }, INGEST_FILE_SPECS.conversation)).toBe(
      '会話ログはJSONファイルを選んでください',
    )
  })

  it('取り込み失敗を利用者向けに区別し、技術詳細は返さない', () => {
    expect(tutorIngestErrorMessage(
      new ApiError(400, { detail: { code: 'blocked_url', message: 'blocked 10.0.0.1' } }),
      'url',
    )).toBe('このURLは安全のため取り込めません')
    expect(tutorIngestErrorMessage(
      new ApiError(422, {
        detail: { code: 'transcript_unavailable', message: 'raw', available_languages: ['en', 'ja'] },
      }),
      'youtube',
    )).toBe('指定した言語の字幕がありません（利用できる言語: en, ja）')
    expect(tutorIngestErrorMessage(
      new ApiError(422, { detail: { code: 'ocr_required', message: 'traceback' } }),
      'pdf',
    )).toBe('文字データが少ないPDFは取り込めません')
    expect(tutorIngestErrorMessage(
      new ApiError(400, { detail: { code: 'malformed_subtitle', message: 'line 3' } }),
      'subtitle',
    )).toBe('字幕ファイルを読み取れませんでした')
    expect(tutorIngestErrorMessage(
      new ApiError(503, { detail: { code: 'transcription_not_configured', message: 'OPENAI_API_KEY' } }),
      'audio',
    )).toBe('文字起こしの設定がありません。管理者に連絡してください')
    expect(tutorIngestErrorMessage(
      new ApiError(502, { detail: { code: 'transcription_provider_error', message: 'stack' } }),
      'audio',
    )).toBe('文字起こしに失敗しました。時間をおいて再度お試しください')
    expect(tutorIngestErrorMessage(new ApiError(404, { detail: 'Not Found' }), 'audio')).toBe(
      '音声の文字起こしはまだ使えません',
    )
    expect(tutorIngestErrorMessage(new Error('network'), 'url')).toBe(
      '取り込みに失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

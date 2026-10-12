import { ApiError } from '../api/tutor'
import type { SourceDocument, SourceSegment } from '../types'
import { formatTutorDateTime } from './tutor'

/** 教材追加画面の入口。API の source_type とは 1:1 にしない。 */
export type SourceAddKind = 'manual' | 'url' | 'pdf' | 'youtube' | 'audio' | 'conversation'

export type YoutubeInputMode = 'url' | 'subtitle'

export type ConversationInputMode = 'text-file' | 'log'

export type IngestFileSlot = 'pdf' | 'subtitle' | 'audio' | 'text' | 'conversation'

export type IngestErrorFamily =
  | 'url'
  | 'pdf'
  | 'youtube'
  | 'subtitle'
  | 'text-file'
  | 'conversation'
  | 'audio'

export const PDF_MAX_BYTES = 8_000_000
export const TEXT_MAX_BYTES = 2_000_000
export const AUDIO_MAX_BYTES = 25_000_000

const SOURCE_TYPE_LABELS: Record<string, string> = {
  manual_text: 'テキスト',
  web_url: 'Web',
  pdf: 'PDF',
  youtube_transcript: 'YouTube',
  subtitle: '字幕',
  audio_transcript: '音声',
  conversation_log: '会話',
}

export interface IngestFileSpec {
  slot: IngestFileSlot
  extensions: readonly string[]
  maxBytes: number
  accept: string
  hint: string
  formatMessage: string
  sizeMessage: string
}

function limitLabel(bytes: number): string {
  const mb = Math.round((bytes / 1_000_000) * 10) / 10
  return `${Number.isInteger(mb) ? String(mb) : mb.toFixed(1)}MB`
}

function fileSpec(
  slot: IngestFileSlot,
  extensions: readonly string[],
  maxBytes: number,
  accept: string,
  hint: string,
  formatMessage: string,
  sizeKind: string,
): IngestFileSpec {
  return {
    slot,
    extensions,
    maxBytes,
    accept,
    hint,
    formatMessage,
    sizeMessage: `${sizeKind}のサイズが上限（${limitLabel(maxBytes)}）を超えています`,
  }
}

export const INGEST_FILE_SPECS: Record<IngestFileSlot, IngestFileSpec> = {
  pdf: fileSpec(
    'pdf',
    ['.pdf'],
    PDF_MAX_BYTES,
    '.pdf,application/pdf',
    `文字が入ったPDFを選べます。画像だけのPDFは取り込めません（${limitLabel(PDF_MAX_BYTES)}まで）`,
    'PDF以外のファイルは取り込めません',
    'PDF',
  ),
  subtitle: fileSpec(
    'subtitle',
    ['.srt', '.vtt'],
    TEXT_MAX_BYTES,
    '.srt,.vtt,text/vtt,application/x-subrip',
    `SRTまたはVTTの字幕ファイルを選べます（${limitLabel(TEXT_MAX_BYTES)}まで）`,
    'SRTまたはVTT以外は取り込めません',
    '字幕ファイル',
  ),
  audio: fileSpec(
    'audio',
    ['.mp3', '.m4a', '.wav', '.webm', '.mp4', '.mpeg', '.mpga', '.ogg', '.flac', '.aac'],
    AUDIO_MAX_BYTES,
    'audio/*,.mp3,.m4a,.wav,.webm,.mp4,.mpeg,.mpga,.ogg,.flac,.aac',
    `音声を文字起こしして教材にします（${limitLabel(AUDIO_MAX_BYTES)}まで）`,
    'この音声形式は取り込めません',
    '音声ファイル',
  ),
  text: fileSpec(
    'text',
    ['.txt', '.md', '.markdown', '.log'],
    TEXT_MAX_BYTES,
    '.txt,.md,.markdown,.log,text/plain,text/markdown',
    `テキストまたはMarkdownを選べます。ファイル内のリンク先は開きません（${limitLabel(TEXT_MAX_BYTES)}まで）`,
    'テキストまたはMarkdown以外は取り込めません',
    'テキストファイル',
  ),
  conversation: fileSpec(
    'conversation',
    ['.json'],
    TEXT_MAX_BYTES,
    '.json,application/json',
    `話者と発言の入ったJSONファイルを選べます。JSONを画面に書く必要はありません（${limitLabel(TEXT_MAX_BYTES)}まで）`,
    '会話ログはJSONファイルを選んでください',
    '会話ログ',
  ),
}

export const MISSING_FILE_MESSAGE = 'ファイルを選択してください'
export const EMPTY_FILE_MESSAGE = 'ファイルが空です'

export function fileExtension(name: string): string {
  const base = name.trim().split(/[/\\]/).pop() ?? ''
  const dot = base.lastIndexOf('.')
  if (dot < 0) return ''
  return base.slice(dot).toLowerCase()
}

export function validateIngestFile(
  file: { name: string; size: number },
  spec: IngestFileSpec,
): string | null {
  if (file.size <= 0) return EMPTY_FILE_MESSAGE
  if (!spec.extensions.includes(fileExtension(file.name))) return spec.formatMessage
  if (file.size > spec.maxBytes) return spec.sizeMessage
  return null
}

export function validateHttpUrl(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return 'URLを入力してください'
  try {
    const url = new URL(trimmed)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return 'http または https の URL を入力してください'
    }
  } catch {
    return 'http または https の URL を入力してください'
  }
  return null
}

export function activeFileSlot(
  kind: SourceAddKind,
  youtubeMode: YoutubeInputMode,
  conversationMode: ConversationInputMode,
): IngestFileSlot | null {
  if (kind === 'pdf') return 'pdf'
  if (kind === 'audio') return 'audio'
  if (kind === 'youtube' && youtubeMode === 'subtitle') return 'subtitle'
  if (kind === 'conversation' && conversationMode === 'text-file') return 'text'
  if (kind === 'conversation' && conversationMode === 'log') return 'conversation'
  return null
}

export function ingestErrorFamily(
  kind: SourceAddKind,
  youtubeMode: YoutubeInputMode,
  conversationMode: ConversationInputMode,
): IngestErrorFamily | null {
  if (kind === 'url') return 'url'
  if (kind === 'pdf') return 'pdf'
  if (kind === 'audio') return 'audio'
  if (kind === 'youtube') return youtubeMode === 'subtitle' ? 'subtitle' : 'youtube'
  if (kind === 'conversation') {
    return conversationMode === 'log' ? 'conversation' : 'text-file'
  }
  return null
}

export function sourceAddHint(
  kind: SourceAddKind,
  youtubeMode: YoutubeInputMode,
  conversationMode: ConversationInputMode,
): string {
  if (kind === 'manual') return '読んだ・見聞きした文章を貼り付けて保存します'
  if (kind === 'url') return '公開ページのURLを入力します'
  if (kind === 'youtube' && youtubeMode === 'url') {
    return '動画のURLまたは動画IDを入力します。公開されている字幕を使います'
  }
  const slot = activeFileSlot(kind, youtubeMode, conversationMode)
  return slot ? INGEST_FILE_SPECS[slot].hint : ''
}

export function ingestPendingLabel(
  kind: SourceAddKind,
  youtubeMode: YoutubeInputMode,
  conversationMode: ConversationInputMode,
): string {
  if (kind === 'manual') return '保存中...'
  if (kind === 'url') return 'ページを取り込んでいます...'
  if (kind === 'pdf') return 'PDFを取り込んでいます...'
  if (kind === 'audio') return '文字起こししています...'
  if (kind === 'youtube') {
    return youtubeMode === 'subtitle' ? '字幕を取り込んでいます...' : '字幕を取得しています...'
  }
  return conversationMode === 'log' ? '会話ログを取り込んでいます...' : 'テキストを取り込んでいます...'
}

export function ingestSubmitLabel(kind: SourceAddKind): string {
  return kind === 'manual' ? '保存する' : '取り込む'
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes < 1000) return `${Math.round(bytes)} B`
  const unit = bytes < 1_000_000 ? 1000 : 1_000_000
  const suffix = unit === 1000 ? 'KB' : 'MB'
  const rounded = Math.round((bytes / unit) * 10) / 10
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
  return `${text} ${suffix}`
}

function metadataString(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  const value = metadata?.[key]
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function firstHttpUrl(...values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    if (value && isHttpUrl(value)) return value
  }
  return null
}

function positiveInt(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) return null
  return value
}

function displayFilename(name: string | null | undefined): string | null {
  if (!name) return null
  const base = name.split(/[/\\]/).pop()?.trim() ?? ''
  if (!base || base === '.' || base === '..') return null
  return base
}

function shortToken(value: string | null, max = 32): string | null {
  if (!value || value.length > max) return null
  return value
}

/** 一覧と詳細の軽い種別。未知の値は内部名を出さない。 */
export function sourceTypeLabel(
  sourceType: string,
  metadata?: Record<string, unknown> | null,
): string {
  if (sourceType === 'conversation_log') {
    const format = metadataString(metadata, 'source_format')
    if (format === 'plain_text' || format === 'markdown') return 'テキスト'
    return '会話'
  }
  return SOURCE_TYPE_LABELS[sourceType] ?? '教材'
}

export interface ProvenanceFact {
  label: string
  value: string
  href?: string
}

export function sourceProvenanceFacts(source: SourceDocument): ProvenanceFact[] {
  const metadata = source.metadata ?? {}
  const provenance = source.provenance
  const hidden = new Set(
    [
      source.content_hash,
      source.ingestion_version,
      provenance?.original_content_hash,
      provenance?.adapter_version,
      provenance?.provider,
      provenance?.provider_model,
      provenance?.ingestion_version,
      metadataString(metadata, 'file_sha256'),
      metadataString(metadata, 'parser_name'),
      metadataString(metadata, 'parser_version'),
      metadataString(metadata, 'provider'),
      metadataString(metadata, 'provider_version'),
      metadataString(metadata, 'provider_model'),
    ].filter((item): item is string => Boolean(item)),
  )
  const facts: ProvenanceFact[] = []
  const push = (label: string, value: string | null, href?: string) => {
    if (!value || hidden.has(value)) return
    facts.push(href ? { label, value, href } : { label, value })
  }

  const type = source.source_type
  if (type === 'web_url') {
    const finalUrl = firstHttpUrl(
      metadataString(metadata, 'final_url'),
      metadataString(metadata, 'canonical_url'),
      provenance?.canonical_locator,
    )
    const requested = firstHttpUrl(metadataString(metadata, 'requested_url'))
    push('URL', finalUrl, finalUrl ?? undefined)
    if (requested && requested !== finalUrl) push('元のURL', requested, requested)
  } else if (type === 'youtube_transcript') {
    const url = firstHttpUrl(
      metadataString(metadata, 'original_url'),
      provenance?.canonical_locator,
    )
    push('URL', url, url ?? undefined)
  }

  if (type !== 'manual_text' && type !== 'web_url') {
    push('ファイル', displayFilename(provenance?.filename))
  }

  if (type === 'pdf') {
    const pages = positiveInt(metadata.page_count)
    if (pages) push('ページ数', String(pages))
  }

  const transcriptLanguage = shortToken(
    metadataString(metadata, 'transcript_language')
      ?? metadataString(metadata, 'detected_language'),
  )
  if (transcriptLanguage && (type === 'youtube_transcript' || type === 'subtitle')) {
    push('字幕の言語', transcriptLanguage)
  }
  if (transcriptLanguage && type === 'audio_transcript') {
    push('言語', transcriptLanguage)
  }

  const format = metadataString(metadata, 'format')
  if (type === 'subtitle' && format && /^(srt|vtt)$/i.test(format)) {
    push('形式', format.toUpperCase())
  }
  if (metadataString(metadata, 'source_format') === 'markdown') {
    push('形式', 'Markdown')
  }

  return facts
}

function formatClock(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds < 0) return null
  const total = Math.floor(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const ss = String(secs).padStart(2, '0')
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${ss}`
  return `${minutes}:${ss}`
}

function mediaRangeLabel(
  start: number | null | undefined,
  end: number | null | undefined,
): string | null {
  const startLabel = start == null ? null : formatClock(start)
  const endLabel = end == null ? null : formatClock(end)
  if (startLabel && endLabel && startLabel !== endLabel) return `${startLabel}–${endLabel}`
  return startLabel ?? endLabel
}

function formatMaybeDateTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return formatTutorDateTime(value)
}

function isPage(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1
}

function pageLabel(pages: number[]): string | null {
  if (pages.length === 0) return null
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  if (sorted.length === 1) return `${sorted[0]}ページ`
  const contiguous = sorted.every((page, index) => index === 0 || page === sorted[index - 1] + 1)
  if (contiguous) return `${sorted[0]}–${sorted[sorted.length - 1]}ページ`
  return `${sorted.join('、')}ページ`
}

export function segmentProvenanceLabel(segment: SourceSegment): string | null {
  const parts: string[] = []
  const speaker = segment.speaker?.trim()
  if (speaker) parts.push(speaker)
  const time = mediaRangeLabel(segment.start_seconds, segment.end_seconds)
  if (time) parts.push(time)
  else if (segment.timestamp?.trim()) parts.push(formatMaybeDateTime(segment.timestamp.trim()))
  if (isPage(segment.page_number)) parts.push(`${segment.page_number}ページ`)
  return parts.length > 0 ? parts.join(' · ') : null
}

function sliceByCodePoint(text: string, start: number, end: number): string | null {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null
  const chars = [...text]
  if (end > chars.length) return null
  return chars.slice(start, end).join('')
}

export interface SourceContentBlock {
  text: string
  label: string | null
}

/** ページ・時刻・話者があるときだけ本文を区切る。範囲が崩れていたら全文のままにする。 */
export function sourceContentBlocks(source: {
  content: string
  segments?: readonly SourceSegment[] | null
}): SourceContentBlock[] | null {
  const segments = source.segments
  if (!segments || segments.length === 0) return null
  const labels = segments.map(segmentProvenanceLabel)
  if (labels.every(label => label == null)) return null
  const texts: string[] = []
  for (const segment of segments) {
    const text = sliceByCodePoint(source.content, segment.normalized_start, segment.normalized_end)
    if (text == null) return null
    texts.push(text)
  }
  if (texts.join('\n\n') !== source.content) return null
  return texts.map((text, index) => ({ text, label: labels[index] ?? null }))
}

export function evidenceProvenanceLabel(
  segments: readonly SourceSegment[] | null | undefined,
  span: { start: number; end: number },
): string | null {
  if (!segments || segments.length === 0) return null
  const hits = segments.filter(
    segment => span.start < segment.normalized_end && span.end > segment.normalized_start,
  )
  if (hits.length === 0) return null
  const parts: string[] = []
  const speakers: string[] = []
  for (const segment of hits) {
    const speaker = segment.speaker?.trim()
    if (speaker && !speakers.includes(speaker)) speakers.push(speaker)
  }
  if (speakers.length > 0) parts.push(speakers.slice(0, 3).join('、'))
  const starts = hits
    .map(segment => segment.start_seconds)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const ends = hits
    .map(segment => segment.end_seconds)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const time = mediaRangeLabel(
    starts.length > 0 ? Math.min(...starts) : null,
    ends.length > 0 ? Math.max(...ends) : null,
  )
  if (time) parts.push(time)
  else {
    const stamp = hits.map(segment => segment.timestamp?.trim()).find(Boolean)
    if (stamp) parts.push(formatMaybeDateTime(stamp))
  }
  const pages = pageLabel(hits.map(segment => segment.page_number).filter(isPage))
  if (pages) parts.push(pages)
  return parts.length > 0 ? parts.join(' · ') : null
}

interface IngestErrorBody {
  code?: string
  languages: string[]
}

function ingestErrorBody(error: unknown): IngestErrorBody {
  if (!(error instanceof ApiError) || error.body == null || typeof error.body !== 'object') {
    return { languages: [] }
  }
  const detail = (error.body as { detail?: unknown }).detail
  if (detail == null || typeof detail !== 'object' || Array.isArray(detail)) {
    return { languages: [] }
  }
  const record = detail as { code?: unknown; available_languages?: unknown }
  const languages = Array.isArray(record.available_languages)
    ? record.available_languages.filter(
      (item): item is string => typeof item === 'string' && item.trim() !== '',
    )
    : []
  return {
    code: typeof record.code === 'string' ? record.code : undefined,
    languages,
  }
}

function withLanguages(message: string, code: string | undefined, languages: string[]): string {
  if (
    languages.length === 0
    || (code !== 'transcript_unavailable' && code !== 'transcript_disabled' && code !== 'video_unavailable')
  ) {
    return message
  }
  return `${message}（利用できる言語: ${languages.join(', ')}）`
}

function familyCodeMessage(family: IngestErrorFamily, code: string): string | null {
  if (family === 'url') {
    const messages: Record<string, string> = {
      invalid_url: 'URLの形式を確認してください',
      blocked_url: 'このURLは安全のため取り込めません',
      fetch_timeout: 'ページの取得が時間内に終わりませんでした。もう一度お試しください',
      unsupported_content_type: 'このページの形式は取り込めません',
      response_too_large: 'ページが大きすぎて取り込めません',
      extraction_empty: 'ページから本文を取り出せませんでした',
      upstream_error: 'ページの取得に失敗しました。時間をおいて再度お試しください',
      too_many_redirects: 'ページの転送が多すぎて取り込めませんでした',
    }
    return messages[code] ?? null
  }
  if (family === 'pdf') {
    const messages: Record<string, string> = {
      invalid_pdf: 'PDFを読み取れませんでした',
      malformed_pdf: 'PDFを読み取れませんでした',
      encrypted_pdf: 'パスワード付きPDFは取り込めません',
      unsupported_media: 'PDF以外のファイルは取り込めません',
      file_too_large: 'PDFのサイズが上限を超えています',
      too_many_pages: 'ページ数が多すぎて取り込めません',
      text_too_large: '取り出した本文が長すぎます',
      ocr_required: '文字データが少ないPDFは取り込めません',
      parser_timeout: 'PDFの読み取りが時間内に終わりませんでした',
    }
    return messages[code] ?? null
  }
  if (family === 'youtube') {
    const messages: Record<string, string> = {
      invalid_video: 'YouTubeのURLまたは動画IDを確認してください',
      transcript_unavailable: '指定した言語の字幕がありません',
      transcript_disabled: 'この動画では字幕を利用できません',
      video_unavailable: 'この動画の字幕は取得できません',
      malformed_transcript: '字幕を読み取れませんでした',
      transcript_empty: '字幕の本文が空でした',
      text_too_large: '字幕から取り出した本文が長すぎます',
      transcript_timeout: '字幕の取得が時間内に終わりませんでした',
      transcript_provider_error: '字幕の取得に失敗しました。時間をおいて再度お試しください',
    }
    return messages[code] ?? null
  }
  if (family === 'subtitle') {
    const messages: Record<string, string> = {
      invalid_subtitle: '字幕ファイルを読み取れませんでした',
      malformed_subtitle: '字幕ファイルを読み取れませんでした',
      unsupported_media: 'SRTまたはVTT以外は取り込めません',
      file_too_large: '字幕ファイルのサイズが上限を超えています',
      text_too_large: '字幕から取り出した本文が長すぎます',
      subtitle_empty: '字幕の本文が空でした',
    }
    return messages[code] ?? null
  }
  if (family === 'text-file') {
    const messages: Record<string, string> = {
      invalid_text_file: 'テキストファイルを読み取れませんでした',
      malformed_text: 'テキストファイルを読み取れませんでした',
      unsupported_media: 'テキストまたはMarkdown以外は取り込めません',
      file_too_large: 'テキストファイルのサイズが上限を超えています',
      text_too_large: 'テキストから取り出した本文が長すぎます',
      text_empty: 'テキストの本文が空でした',
    }
    return messages[code] ?? null
  }
  if (family === 'conversation') {
    const messages: Record<string, string> = {
      invalid_conversation: '会話ログの形式を読み取れませんでした',
      malformed_conversation: '会話ログの形式を読み取れませんでした',
      unsupported_media: '会話ログはJSONファイルを選んでください',
      file_too_large: '会話ログのサイズが上限を超えています',
      text_too_large: '会話ログから取り出した本文が長すぎます',
      conversation_empty: '会話ログの本文が空でした',
    }
    return messages[code] ?? null
  }
  const messages: Record<string, string> = {
    not_implemented: '音声の文字起こしはまだ使えません',
    transcription_not_configured: '文字起こしの設定がありません。管理者に連絡してください',
    provider_not_configured: '文字起こしの設定がありません。管理者に連絡してください',
    transcription_config_missing: '文字起こしの設定がありません。管理者に連絡してください',
    transcription_provider_error: '文字起こしに失敗しました。時間をおいて再度お試しください',
    provider_error: '文字起こしに失敗しました。時間をおいて再度お試しください',
    transcript_empty: '文字起こし結果が空でした',
    transcription_empty: '文字起こし結果が空でした',
    empty_transcript: '文字起こし結果が空でした',
    transcription_timeout: '文字起こしが時間内に終わりませんでした',
    transcript_timeout: '文字起こしが時間内に終わりませんでした',
    unsupported_media: 'この音声形式は取り込めません',
    unsupported_audio: 'この音声形式は取り込めません',
    file_too_large: '音声ファイルのサイズが上限を超えています',
    audio_too_large: '音声ファイルのサイズが上限を超えています',
    duration_too_long: '音声が長すぎて取り込めません',
    audio_too_long: '音声が長すぎて取り込めません',
  }
  return messages[code] ?? null
}

function statusFallback(family: IngestErrorFamily, status: number): string | null {
  if (family === 'audio' && (status === 404 || status === 501)) {
    return '音声の文字起こしはまだ使えません'
  }
  if (family === 'audio' && status === 503) {
    return '文字起こしの設定がありません。管理者に連絡してください'
  }
  if (status === 413) return 'サイズが上限を超えています'
  if (status === 415) return 'この形式は取り込めません'
  if (status === 422) return '入力内容を確認してください'
  if (status === 502) return '取り込みに失敗しました。時間をおいて再度お試しください'
  if (status === 504) return '取り込みが時間内に終わりませんでした。もう一度お試しください'
  if (status >= 500) return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  return null
}

export function tutorIngestErrorMessage(error: unknown, family: IngestErrorFamily): string {
  const { code, languages } = ingestErrorBody(error)
  if (code) {
    const message = familyCodeMessage(family, code)
    if (message) return withLanguages(message, code, languages)
  }
  if (error instanceof ApiError) {
    const fallback = statusFallback(family, error.status)
    if (fallback) return fallback
  }
  return '取り込みに失敗しました。通信環境を確認して再度お試しください'
}

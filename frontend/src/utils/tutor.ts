import { ApiError, isNotFoundError } from '../api/tutor'

const NOTE_KEY = 'note'

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}

/** Backend は UTC。ブラウザのローカルタイム（または指定 TZ）で自然に表示する。 */
export function formatTutorDateTime(
  iso: string,
  locales: Intl.LocalesArgument = 'ja-JP',
  timeZone?: string,
): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(locales, {
    ...DATE_FORMAT,
    ...(timeZone ? { timeZone } : {}),
  }).format(date)
}

export function tutorFetchErrorMessage(
  error: unknown,
  kind: 'list' | 'detail',
): string {
  if (isNotFoundError(error) && kind === 'detail') {
    return 'Sourceが見つかりません'
  }
  if (error instanceof ApiError && error.status >= 500) {
    return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  }
  return kind === 'list'
    ? '一覧の取得に失敗しました。通信環境を確認して再度お試しください'
    : '詳細の取得に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorNoteFromMetadata(
  metadata: Record<string, unknown> | undefined,
): string | null {
  const note = metadata?.[NOTE_KEY]
  if (typeof note !== 'string') return null
  const trimmed = note.trim()
  return trimmed === '' ? null : trimmed
}

export function tutorNoteMetadata(note: string): Record<string, unknown> {
  const trimmed = note.trim()
  return trimmed === '' ? {} : { [NOTE_KEY]: trimmed }
}

function locIncludes(loc: unknown, field: string): boolean {
  return Array.isArray(loc) && loc.some(part => part === field)
}

export function fieldErrorsFromTutorApiBody(body: unknown): {
  title?: string
  content?: string
} {
  if (!body || typeof body !== 'object') return {}
  const detail = (body as { detail?: unknown }).detail
  if (!Array.isArray(detail)) return {}

  const errors: { title?: string; content?: string } = {}
  for (const item of detail) {
    if (!item || typeof item !== 'object') continue
    const loc = (item as { loc?: unknown }).loc
    if (locIncludes(loc, 'title')) {
      errors.title = 'タイトルを入力してください'
    }
    if (locIncludes(loc, 'content')) {
      errors.content = 'フランス語の本文を入力してください'
    }
  }
  return errors
}

export function tutorSaveErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return '入力内容を確認してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '保存に失敗しました。通信環境を確認して再度お試しください'
}

import { ApiError, isNotFoundError } from '../api/tutor'
import type {
  CandidateStatus,
  ExerciseType,
  ExerciseView,
  LearningItem,
  LearningItemType,
} from '../types'

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

export const LEARNING_ITEM_TYPE_LABELS: Record<LearningItemType, string> = {
  vocabulary: '語彙',
  expression: '表現',
  grammar: '文法',
  conjugation: '活用',
}

export const CANDIDATE_STATUS_LABELS: Record<CandidateStatus, string> = {
  candidate: '未確認',
  accepted: '採用済み',
  rejected: '却下',
}

function apiDetail(error: unknown): string {
  if (!(error instanceof ApiError) || error.body == null || typeof error.body !== 'object') {
    return ''
  }
  const detail = (error.body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : ''
}

export function tutorExtractErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = apiDetail(error)
    if (error.status === 404) {
      return 'Sourceが見つかりません'
    }
    if (error.status === 503) {
      if (/OPENAI_API_KEY|API[_ ]?KEY|設定されて/i.test(detail)) {
        return '学習候補の抽出に必要な設定がありません。管理者に連絡してください'
      }
      if (/rate/i.test(detail)) {
        return '混み合っているため、しばらくしてから再度お試しください'
      }
      return '一時的に抽出できません。時間をおいて再度お試しください'
    }
    if (error.status === 502) {
      return '学習候補をうまく読み取れませんでした。もう一度抽出してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '学習候補の抽出に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorCandidateFetchErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return 'Sourceが見つかりません'
  }
  if (error instanceof ApiError && error.status >= 500) {
    return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  }
  return '学習候補の取得に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorCandidateActionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '候補が見つかりません'
    }
    if (error.status === 409) {
      return 'この候補はすでに処理されています'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '操作に失敗しました。通信環境を確認して再度お試しください'
}

export function formatCandidateConfidence(confidence: number | null): string | null {
  if (confidence == null) return null
  return `確信度 ${Math.round(confidence * 100)}%`
}

export const EXERCISE_TYPE_LABELS: Record<ExerciseType, string> = {
  meaning_recognition: '意味',
  fr_to_ja: '和訳',
  ja_to_fr: '仏作文',
  cloze: '穴埋め',
  expression_reconstruction: '並べ替え',
  verb_conjugation: '活用',
  noun_gender: '名詞の性',
  noun_article: '冠詞',
}

export function tutorPracticeSessionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '教材または学習項目が見つかりません'
    }
    if (error.status === 422) {
      return '練習の条件を確認してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '練習の開始に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorExerciseAnswerErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '学習項目が見つかりません'
    }
    if (error.status === 409) {
      return 'この回答はすでに記録されています'
    }
    if (error.status === 422) {
      return '回答の形式を確認してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '判定に失敗しました。通信環境を確認して再度お試しください'
}

export function looksLikeFrench(text: string): boolean {
  return /[A-Za-zÀ-ÿ]/.test(text)
}

export function formatPracticeGiven(given: string | string[]): string {
  return Array.isArray(given) ? given.join(' ') : given
}

/** フランス語として自然な TTS 対象。日本語の意味は含めない。 */
export function practiceFrenchTtsTargets(
  exercise: ExerciseView,
  item: LearningItem | undefined,
  correctAnswer: string | null,
): string[] {
  const texts: string[] = []
  const push = (text: string | null | undefined) => {
    const trimmed = text?.trim()
    if (!trimmed || !looksLikeFrench(trimmed)) return
    if (!texts.includes(trimmed)) texts.push(trimmed)
  }
  push(item?.canonical_form)
  if (exercise.exercise_type !== 'meaning_recognition') {
    push(correctAnswer)
  }
  return texts
}

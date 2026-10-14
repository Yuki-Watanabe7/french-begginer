import { ApiError, isNotFoundError } from '../api/tutor'
import type {
  ActivityKind,
  CandidateStatus,
  ExerciseType,
  ExerciseView,
  LearningItem,
  LearningItemType,
  ReasonCode,
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

export function tutorKnownItemErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return '学習項目が見つかりません'
  }
  if (error instanceof ApiError && error.status >= 500) {
    return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  }
  return '操作に失敗しました。通信環境を確認して再度お試しください'
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

export function tutorReviewQueueErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status >= 500) {
    return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  }
  return '復習一覧の取得に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorReviewSessionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return '復習の条件を確認してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '復習の開始に失敗しました。通信環境を確認して再度お試しください'
}

export const DEFAULT_TODAY_QUESTION_COUNT = 10
export const DEFAULT_TODAY_MAX_NEW_COUNT = 3
export const MAX_VISIBLE_REASON_COUNT = 2
export const MAX_TODAY_PLAN_PREVIEW = 3

/** reason code → 短いユーザー向け文言。内部 score は載せない。 */
export const REASON_CODE_LABELS: Record<ReasonCode, string> = {
  OVERDUE_REVIEW: '復習時期を迎えています',
  RECENT_ERROR: '最近この表現で間違えています',
  PRODUCTION_WEAKER: '意味は分かっていますが、自分で言う練習を優先します',
  RECOGNITION_WEAKER: '自分では言えますが、意味を素早く捉える練習を優先します',
  LOW_MASTERY: 'まだ定着が十分ではありません',
  LAPSE_RISK: '以前つまずいた項目です',
  RECENT_SOURCE: '最近追加した教材に出てきた表現です',
  LEVEL_FIT: '現在の学習レベルに近い項目です',
  HIGH_INTEREST: '関心の高い教材に出てきた表現です',
  HIGH_IMPORTANCE: '優先して覚えたい項目です',
  PATTERN_RECENT_ERRORS: '最近、同じ種類の項目で間違いが続いています',
  PRODUCTION_PATTERN_WEAKNESS: '最近、同じ種類の項目の自力回答で間違いが続いています',
}

const PATTERN_REASON_CODES = new Set<ReasonCode>([
  'PATTERN_RECENT_ERRORS',
  'PRODUCTION_PATTERN_WEAKNESS',
])

const KNOWN_REASON_CODES = new Set<string>(Object.keys(REASON_CODE_LABELS))

export function isReasonCode(value: string): value is ReasonCode {
  return KNOWN_REASON_CODES.has(value)
}

/** 上位 1〜2 件だけ返す。未知 code や空は捏造しない。 */
export function visibleReasonLabels(
  codes: readonly string[] | null | undefined,
  limit = MAX_VISIBLE_REASON_COUNT,
): string[] {
  if (!codes || codes.length === 0) return []
  const labels: string[] = []
  for (const code of codes) {
    if (!isReasonCode(code)) continue
    const label = REASON_CODE_LABELS[code]
    if (!labels.includes(label)) labels.push(label)
    if (labels.length >= limit) break
  }
  return labels
}

/** 苦手パターンは項目名を含む explanation を、それ以外は短いラベルを出す。 */
export function visibleEntryReasons(
  entry:
    | {
        reason_codes?: readonly string[] | null
        explanation?: string | null
      }
    | null
    | undefined,
): string[] {
  if (!entry?.reason_codes || entry.reason_codes.length === 0) return []
  const hasPattern = entry.reason_codes.some(
    code => isReasonCode(code) && PATTERN_REASON_CODES.has(code),
  )
  const explanation = entry.explanation?.trim()
  if (hasPattern && explanation) return [explanation]
  return visibleReasonLabels(entry.reason_codes)
}

export function todayActivityLabel(kind: ActivityKind): string {
  return kind === 'review' ? '復習' : '新しい項目'
}

export function tutorTodayPlanErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status >= 500) {
    return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
  }
  return '今日の学習の取得に失敗しました。通信環境を確認して再度お試しください'
}

export function tutorTodaySessionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return '今日の学習の条件を確認してください'
    }
    if (error.status >= 500) {
      return 'サーバーでエラーが発生しました。時間をおいて再度お試しください'
    }
  }
  return '今日の学習の開始に失敗しました。通信環境を確認して再度お試しください'
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

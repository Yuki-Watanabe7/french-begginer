import { describe, it, expect } from 'vitest'
import { ApiError } from '../api/tutor'
import {
  fieldErrorsFromTutorApiBody,
  formatCandidateConfidence,
  formatTutorDateTime,
  tutorCandidateActionErrorMessage,
  tutorExtractErrorMessage,
  tutorFetchErrorMessage,
  tutorNoteFromMetadata,
  tutorNoteMetadata,
  tutorSaveErrorMessage,
} from '../utils/tutor'

describe('formatTutorDateTime', () => {
  it('UTC の時刻を指定タイムゾーンのローカル表示にする', () => {
    const tokyo = formatTutorDateTime(
      '2026-08-23T15:30:00+00:00',
      'en-GB',
      'Asia/Tokyo',
    )
    expect(tokyo).toMatch(/24 Aug 2026/)
    expect(tokyo).toMatch(/00:30/)
  })

  it('timezone を固定すると同じ入力で同じ結果になる', () => {
    const utc = formatTutorDateTime(
      '2026-08-23T12:00:00+00:00',
      'en-GB',
      'UTC',
    )
    expect(utc).toMatch(/23 Aug 2026/)
    expect(utc).toMatch(/12:00/)
  })

  it('不正な日時は元の文字列を返す', () => {
    expect(formatTutorDateTime('not-a-date')).toBe('not-a-date')
  })
})

describe('tutorFetchErrorMessage', () => {
  it('一覧と詳細の通信失敗を日本語へ変換する', () => {
    expect(tutorFetchErrorMessage(new Error('network'), 'list')).toBe(
      '一覧の取得に失敗しました。通信環境を確認して再度お試しください',
    )
    expect(tutorFetchErrorMessage(new Error('network'), 'detail')).toBe(
      '詳細の取得に失敗しました。通信環境を確認して再度お試しください',
    )
    expect(tutorFetchErrorMessage(new ApiError(500), 'list')).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
    expect(tutorFetchErrorMessage(new ApiError(404, { detail: 'missing' }), 'detail')).toBe(
      'Sourceが見つかりません',
    )
  })
})

describe('tutorNoteMetadata', () => {
  it('空や空白のみなら metadata を付けない', () => {
    expect(tutorNoteMetadata('')).toEqual({})
    expect(tutorNoteMetadata('  \n')).toEqual({})
  })

  it('前後空白を除いて note を保存する', () => {
    expect(tutorNoteMetadata('  新聞  ')).toEqual({ note: '新聞' })
  })
})

describe('tutorNoteFromMetadata', () => {
  it('note 文字列だけを取り出す', () => {
    expect(tutorNoteFromMetadata({ note: '社説' })).toBe('社説')
    expect(tutorNoteFromMetadata({ note: '  ' })).toBeNull()
    expect(tutorNoteFromMetadata({ origin: 'hand' })).toBeNull()
    expect(tutorNoteFromMetadata(undefined)).toBeNull()
  })
})

describe('tutorSaveErrorMessage', () => {
  it('422 / 5xx / その他を日本語へ変換する', () => {
    expect(tutorSaveErrorMessage(new ApiError(422, { detail: 'x' }))).toBe(
      '入力内容を確認してください',
    )
    expect(tutorSaveErrorMessage(new ApiError(500))).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
    expect(tutorSaveErrorMessage(new Error('network'))).toBe(
      '保存に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('fieldErrorsFromTutorApiBody', () => {
  it('FastAPI の loc から title / content を拾う', () => {
    expect(
      fieldErrorsFromTutorApiBody({
        detail: [
          { loc: ['body', 'title'], msg: 'too short' },
          { loc: ['body', 'content'], msg: 'too short' },
        ],
      }),
    ).toEqual({
      title: 'タイトルを入力してください',
      content: 'フランス語の本文を入力してください',
    })
  })
})

describe('tutorExtractErrorMessage', () => {
  it('API key / 混雑 / 不正応答 / 通信失敗を日本語へ変換する', () => {
    expect(
      tutorExtractErrorMessage(
        new ApiError(503, { detail: 'OPENAI_API_KEY が設定されていない' }),
      ),
    ).toBe('学習候補の抽出に必要な設定がありません。管理者に連絡してください')
    expect(
      tutorExtractErrorMessage(new ApiError(503, { detail: 'rate limited' })),
    ).toBe('混み合っているため、しばらくしてから再度お試しください')
    expect(tutorExtractErrorMessage(new ApiError(502, { detail: 'bad json' }))).toBe(
      '学習候補をうまく読み取れませんでした。もう一度抽出してください',
    )
    expect(tutorExtractErrorMessage(new Error('network'))).toBe(
      '学習候補の抽出に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('tutorCandidateActionErrorMessage', () => {
  it('409 / 5xx を日本語へ変換する', () => {
    expect(tutorCandidateActionErrorMessage(new ApiError(409, { detail: 'rejected' }))).toBe(
      'この候補はすでに処理されています',
    )
    expect(tutorCandidateActionErrorMessage(new ApiError(500))).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
  })
})

describe('formatCandidateConfidence', () => {
  it('0.9 をパーセント表示し、null は出さない', () => {
    expect(formatCandidateConfidence(0.9)).toBe('確信度 90%')
    expect(formatCandidateConfidence(null)).toBeNull()
  })
})

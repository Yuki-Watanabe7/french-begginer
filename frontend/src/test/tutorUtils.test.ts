import { describe, it, expect } from 'vitest'
import { ApiError } from '../api/tutor'
import {
  fieldErrorsFromTutorApiBody,
  tutorNoteFromMetadata,
  tutorNoteMetadata,
  tutorSaveErrorMessage,
} from '../utils/tutor'

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

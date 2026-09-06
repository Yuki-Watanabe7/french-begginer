import { describe, it, expect } from 'vitest'
import { ApiError } from '../api/tutor'
import {
  fieldErrorsFromTutorApiBody,
  formatCandidateConfidence,
  formatPracticeGiven,
  formatTutorDateTime,
  looksLikeFrench,
  practiceFrenchTtsTargets,
  tutorCandidateActionErrorMessage,
  tutorExerciseAnswerErrorMessage,
  tutorExtractErrorMessage,
  tutorFetchErrorMessage,
  tutorNoteFromMetadata,
  tutorNoteMetadata,
  tutorPracticeSessionErrorMessage,
  tutorReviewQueueErrorMessage,
  tutorReviewSessionErrorMessage,
  tutorSaveErrorMessage,
  tutorTodayPlanErrorMessage,
  tutorTodaySessionErrorMessage,
  visibleReasonLabels,
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

describe('tutorPracticeSessionErrorMessage', () => {
  it('404 / 422 / 通信失敗を日本語へ変換する', () => {
    expect(tutorPracticeSessionErrorMessage(new ApiError(404))).toBe(
      '教材または学習項目が見つかりません',
    )
    expect(tutorPracticeSessionErrorMessage(new ApiError(422))).toBe(
      '練習の条件を確認してください',
    )
    expect(tutorPracticeSessionErrorMessage(new Error('network'))).toBe(
      '練習の開始に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('tutorReviewQueueErrorMessage', () => {
  it('5xx / 通信失敗を日本語へ変換する', () => {
    expect(tutorReviewQueueErrorMessage(new ApiError(500))).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
    expect(tutorReviewQueueErrorMessage(new Error('network'))).toBe(
      '復習一覧の取得に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('tutorReviewSessionErrorMessage', () => {
  it('422 / 通信失敗を日本語へ変換する', () => {
    expect(tutorReviewSessionErrorMessage(new ApiError(422))).toBe(
      '復習の条件を確認してください',
    )
    expect(tutorReviewSessionErrorMessage(new Error('network'))).toBe(
      '復習の開始に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('visibleReasonLabels', () => {
  it('reason code を短いユーザー文言へ変換する', () => {
    expect(visibleReasonLabels(['OVERDUE_REVIEW'])).toEqual(['復習時期を迎えています'])
    expect(visibleReasonLabels(['RECENT_ERROR'])).toEqual(['最近この表現で間違えています'])
    expect(visibleReasonLabels(['PRODUCTION_WEAKER'])).toEqual([
      '意味は分かっていますが、自分で言う練習を優先します',
    ])
    expect(visibleReasonLabels(['RECENT_SOURCE'])).toEqual([
      '最近追加した教材に出てきた表現です',
    ])
    expect(visibleReasonLabels(['LEVEL_FIT'])).toEqual(['現在の学習レベルに近い項目です'])
  })

  it('未設定なら理由を捏造しない', () => {
    expect(visibleReasonLabels([])).toEqual([])
    expect(visibleReasonLabels(undefined)).toEqual([])
    expect(visibleReasonLabels(['UNKNOWN_SCORE' as never])).toEqual([])
    expect(visibleReasonLabels(['HIGH_INTEREST'])).toEqual([
      '関心の高い教材に出てきた表現です',
    ])
  })

  it('1 Item あたり上位2件までに絞る', () => {
    expect(
      visibleReasonLabels(['OVERDUE_REVIEW', 'RECENT_ERROR', 'LOW_MASTERY', 'LEVEL_FIT']),
    ).toEqual(['復習時期を迎えています', '最近この表現で間違えています'])
  })
})

describe('tutorTodayPlanErrorMessage', () => {
  it('5xx / 通信失敗を日本語へ変換する', () => {
    expect(tutorTodayPlanErrorMessage(new ApiError(500))).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
    expect(tutorTodayPlanErrorMessage(new Error('network'))).toBe(
      '今日の学習の取得に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('tutorTodaySessionErrorMessage', () => {
  it('422 / 通信失敗を日本語へ変換する', () => {
    expect(tutorTodaySessionErrorMessage(new ApiError(422))).toBe(
      '今日の学習の条件を確認してください',
    )
    expect(tutorTodaySessionErrorMessage(new Error('network'))).toBe(
      '今日の学習の開始に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('tutorExerciseAnswerErrorMessage', () => {
  it('409 / 5xx を日本語へ変換する', () => {
    expect(tutorExerciseAnswerErrorMessage(new ApiError(409))).toBe(
      'この回答はすでに記録されています',
    )
    expect(tutorExerciseAnswerErrorMessage(new ApiError(500))).toBe(
      'サーバーでエラーが発生しました。時間をおいて再度お試しください',
    )
    expect(tutorExerciseAnswerErrorMessage(new Error('network'))).toBe(
      '判定に失敗しました。通信環境を確認して再度お試しください',
    )
  })
})

describe('practiceFrenchTtsTargets', () => {
  const exercise = {
    learning_item_id: 'item-1',
    exercise_type: 'meaning_recognition' as const,
    skill_direction: 'recognition' as const,
    prompt: 'livre',
    response_kind: 'choice' as const,
    options: ['本'],
    source_context: null,
    exercise_version: 'exercise-v1',
  }
  const item = {
    id: 'item-1',
    item_type: 'vocabulary' as const,
    canonical_form: 'livre',
    meaning_ja: '本',
    explanation_ja: null,
    level: null,
    source_refs: [],
    created_at: '2026-08-24T12:00:00+00:00',
    status: 'active',
  }

  it('日本語の意味は TTS 対象にしない', () => {
    expect(looksLikeFrench('本')).toBe(false)
    expect(practiceFrenchTtsTargets(exercise, item, '本')).toEqual(['livre'])
  })

  it('production の正解はフランス語なら対象にする', () => {
    const jaToFr = { ...exercise, exercise_type: 'ja_to_fr' as const, response_kind: 'text' as const }
    expect(practiceFrenchTtsTargets(jaToFr, item, 'livre')).toEqual(['livre'])
  })
})

describe('formatPracticeGiven', () => {
  it('配列は空白区切りにする', () => {
    expect(formatPracticeGiven(['se', 'rendre'])).toBe('se rendre')
    expect(formatPracticeGiven('livre')).toBe('livre')
  })
})

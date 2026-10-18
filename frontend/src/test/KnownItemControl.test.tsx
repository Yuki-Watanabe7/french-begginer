import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TutorCandidateCard } from '../components/TutorCandidateCard'
import type { LearningItemCandidate } from '../types'

function candidate(
  overrides: Partial<LearningItemCandidate> = {},
): LearningItemCandidate {
  return {
    id: 'cand-1',
    source_document_id: 'src-1',
    item_type: 'vocabulary',
    canonical_form: 'livre',
    meaning_ja: '本',
    explanation_ja: null,
    level: 'A1',
    evidence_span: { start: 0, end: 5 },
    evidence_text: 'livre',
    confidence: 0.8,
    status: 'accepted',
    extraction_version: 'extract-v1',
    created_at: '2026-10-12T12:00:00+00:00',
    learning_item_id: 'item-1',
    explicit_known: false,
    ...overrides,
  }
}

describe('TutorCandidateCard — known item', () => {
  it('採用後に既知を確認してから外す', async () => {
    const onMark = vi.fn()
    render(
      <TutorCandidateCard
        candidate={candidate()}
        isBusy={false}
        actionError={null}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        known={{
          explicitKnown: false,
          busy: false,
          error: null,
          onMark,
          onUndo: vi.fn(),
        }}
      />,
    )
    expect(screen.queryByText(/mastered/i)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'これは知っている' }))
    expect(onMark).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '外す' }))
    expect(onMark).toHaveBeenCalledTimes(1)
  })

  it('既知の候補は表示と取り消しを出す', async () => {
    const onUndo = vi.fn()
    render(
      <TutorCandidateCard
        candidate={candidate({ explicit_known: true })}
        isBusy={false}
        actionError={null}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        known={{
          explicitKnown: true,
          busy: false,
          error: null,
          onMark: vi.fn(),
          onUndo,
        }}
      />,
    )
    expect(screen.getByText('知っているので、新しい学習には出しません')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '元に戻す' }))
    expect(onUndo).toHaveBeenCalledTimes(1)
  })

  it('未確認の候補には既知ボタンを出さない', () => {
    render(
      <TutorCandidateCard
        candidate={candidate({ status: 'candidate', learning_item_id: null })}
        isBusy={false}
        actionError={null}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        known={{
          explicitKnown: false,
          busy: false,
          error: null,
          onMark: vi.fn(),
          onUndo: vi.fn(),
        }}
      />,
    )
    expect(screen.queryByRole('button', { name: 'これは知っている' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '採用する' })).toBeInTheDocument()
  })
})

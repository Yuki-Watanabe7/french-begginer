import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import synthetic from '../../../docs/operations/public-snapshot.synthetic.json'
import ReadonlyViewer from '../readonly/ReadonlyViewer'
import { parseSnapshot, SnapshotFormatError } from '../readonly/snapshot'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function serve(payload: unknown = synthetic) {
  return vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, json: async () => payload,
  }))
}

describe('public-v1 validation', () => {
  it('accepts the synthetic snapshot verified against the #221 exporter', () => {
    expect(parseSnapshot(synthetic)).toEqual(synthetic)
  })

  it.each([
    null, [], {},
    { ...synthetic, schema_version: 'private-v1' },
    { ...synthetic, generated_at: '2026-02-30T09:30:00Z' },
    { ...synthetic, generated_at: '2026-11-03T09:30:00+09:00' },
    { ...synthetic, generated_at: null },
    { ...synthetic, source_document: 'private' },
    { ...synthetic, cards: [] },
    { ...synthetic, cards: Array(501).fill(synthetic.cards[0]) },
    { ...synthetic, cards: [synthetic.cards[0], synthetic.cards[0]] },
    ...[
      { card_id: 'internal-db-id' },
      { item_type: 'unknown' },
      { canonical_form: '' },
      { canonical_form: 'é'.repeat(201) },
      { meaning_ja: 123 },
      { meaning_ja: '文'.repeat(501) },
      { explanation_ja: null },
      { explanation_ja: '文'.repeat(2001) },
      { level: 'D1' },
      { level: null },
      { metadata: { secret: 'not for distribution' } },
      { canonical_form: '<img src=x onerror=alert(1)>' },
      { meaning_ja: 'https://example.com' },
      { meaning_ja: 'test@example.com' },
      { meaning_ja: 'x'.repeat(32) },
      { meaning_ja: 'hello\tworld' },
    ].map(overrides => ({ ...synthetic, cards: [{ ...synthetic.cards[0], ...overrides }] })),
  ])('rejects an invalid snapshot without echoing its contents (%#)', payload => {
    expect(() => parseSnapshot(payload)).toThrow(SnapshotFormatError)
  })

  it('accepts all types, optional fields, newlines and the 500 card limit', () => {
    const cards = Array.from({ length: 500 }, (_, index) => ({
      card_id: `card-${String(index + 1).padStart(3, '0')}`,
      item_type: ['vocabulary', 'expression', 'grammar', 'conjugation'][index % 4],
      canonical_form: 'à bientôt', meaning_ja: 'また\n会いましょう',
    }))
    expect(parseSnapshot({ ...synthetic, cards }).cards).toHaveLength(500)
  })
})

describe('standalone read-only viewer', () => {
  it('shows cards, answers and export time using only the sibling JSON; writes nothing', async () => {
    serve()
    const store = vi.spyOn(Storage.prototype, 'setItem')
    const user = userEvent.setup()
    render(<ReadonlyViewer />)
    expect(screen.getByRole('status')).toHaveTextContent('読み込んでいます')
    expect(await screen.findByRole('heading', { name: 'bonjour' })).toHaveAttribute('lang', 'fr')
    expect(screen.getByRole('heading', { name: "s'il vous plaît" })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'nous parlons' })).toBeInTheDocument()
    expect(screen.getByText('2026-11-03 09:30:00 UTC')).toHaveAttribute('dateTime', synthetic.generated_at)
    expect(screen.getByText(/書き出した時点/)).toBeInTheDocument()
    const toggle = screen.getAllByText('答えを見る・閉じる')[0]
    const details = toggle.closest('details')!
    expect(details.open).toBe(false)
    await user.click(toggle)
    expect(details.open).toBe(true)
    expect(screen.getByText('こんにちは')).toBeVisible()
    await user.click(toggle)
    expect(details.open).toBe(false)
    expect(fetch).toHaveBeenCalledExactlyOnceWith('./snapshot.json', {
      cache: 'no-store', credentials: 'omit', redirect: 'error', signal: expect.any(AbortSignal),
    })
    expect(store).not.toHaveBeenCalled()
  })

  it.each(['http', 'network', 'json', 'schema'])('shows a recoverable error on %s failure', async failure => {
    const fetchMock = vi.fn()
    if (failure === 'network') fetchMock.mockRejectedValueOnce(new Error('private server detail'))
    else fetchMock.mockResolvedValueOnce({
      ok: failure !== 'http',
      json: async () => {
        if (failure === 'json') throw new SyntaxError('private malformed input')
        return { ...synthetic, schema_version: 'unknown' }
      },
    })
    fetchMock.mockResolvedValue({ ok: true, json: async () => synthetic })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<ReadonlyViewer />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      failure === 'json' || failure === 'schema' ? '形式が正しくありません' : '読み込めませんでした',
    )
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByText(/private/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '再読み込み' }))
    expect(await screen.findByRole('heading', { name: 'bonjour' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not interpret card text as HTML', async () => {
    serve({ ...synthetic, cards: [{
      ...synthetic.cards[0], canonical_form: 'a < b & c > d',
    }] })
    const { container } = render(<ReadonlyViewer />)
    expect(await screen.findByRole('heading', { name: 'a < b & c > d' })).toBeInTheDocument()
    expect(container.querySelector('h2')?.children).toHaveLength(0)
  })

  it('cancels a pending request when leaving the viewer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise(() => {})))
    const { unmount } = render(<ReadonlyViewer />)
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    const signal = vi.mocked(fetch).mock.calls[0][1]!.signal!
    unmount()
    expect(signal.aborted).toBe(true)
  })

  it('turns a stalled request into an error after ten seconds', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, options: RequestInit) => new Promise((_, reject) => {
      options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    render(<ReadonlyViewer />)
    const { act } = await import('@testing-library/react')
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    expect(screen.getByRole('alert')).toHaveTextContent('読み込めませんでした')
  })
})

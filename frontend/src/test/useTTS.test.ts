import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTTS } from '../hooks/useTTS'

const mockAudioPlay = vi.fn().mockResolvedValue(undefined)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const MockAudio = vi.fn().mockImplementation(function (this: any) {
  this.play = mockAudioPlay
})

function mockSuccessResponse(): Response {
  return {
    ok: true,
    blob: () => Promise.resolve(new Blob()),
  } as unknown as Response
}

function mockErrorResponse(status: number): Response {
  return { ok: false, status } as unknown as Response
}

beforeEach(() => {
  vi.stubGlobal('Audio', MockAudio)
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn().mockReturnValue('blob:mock-url'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  })
  globalThis.fetch = vi.fn()
  mockAudioPlay.mockClear()
  MockAudio.mockClear()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('useTTS', () => {
  it('初期状態: isLoading=false, error=null', () => {
    const { result } = renderHook(() => useTTS())
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('fetchが成功した場合、isLoadingはfalseに戻りerrorはnull', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockSuccessResponse())

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play('un livre')
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('fetchが成功した場合、Audio.playが呼ばれる', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockSuccessResponse())

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play('un livre')
    })

    expect(mockAudioPlay).toHaveBeenCalled()
  })

  it('fetchが404を返した場合、errorがセットされる', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockErrorResponse(404))

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play('un livre')
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBe('音声を読み込めませんでした')
  })

  it('fetchが503を返した場合、errorがセットされる', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockErrorResponse(503))

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play('un livre')
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBe('音声を読み込めませんでした')
  })

  it('fetchが例外をthrowした場合、errorがセットされる', async () => {
    vi.mocked(globalThis.fetch).mockRejectedValueOnce(new Error('network error'))

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play('un livre')
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBe('音声の再生に失敗しました')
  })

  it('ロード中に再度playを呼んでも多重実行されない', async () => {
    let resolveFetch!: (v: Response) => void
    const fetchPromise = new Promise<Response>(resolve => { resolveFetch = resolve })
    vi.mocked(globalThis.fetch).mockReturnValueOnce(fetchPromise)

    const { result } = renderHook(() => useTTS())

    act(() => { result.current.play('un livre') })
    act(() => { result.current.play('une maison') })

    await act(async () => {
      resolveFetch(mockSuccessResponse())
      await fetchPromise
    })

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1)
  })

  it("fetchのURLにtextパラメータがエンコードされて渡される（l'école）", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockSuccessResponse())

    const { result } = renderHook(() => useTTS())
    await act(async () => {
      await result.current.play("l'école")
    })

    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      expect.stringContaining("l'%C3%A9cole"),
    )
  })
})

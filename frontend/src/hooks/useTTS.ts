import { useCallback, useRef, useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export function useTTS() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isLoadingRef = useRef(false)
  const blobUrlRef = useRef<string | null>(null)

  const clearError = useCallback(() => setError(null), [])

  const play = useCallback(async (text: string) => {
    if (isLoadingRef.current) return

    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = null
    }

    isLoadingRef.current = true
    setIsLoading(true)
    setError(null)

    try {
      const res = await fetch(`${BASE}/api/tts/speak?text=${encodeURIComponent(text)}`)
      if (!res.ok) {
        setError('音声を読み込めませんでした')
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      await audio.play()
    } catch {
      setError('音声の再生に失敗しました')
    } finally {
      isLoadingRef.current = false
      setIsLoading(false)
    }
  }, [])

  return { play, isLoading, error, clearError }
}

import { useCallback, useRef, useState } from 'react'
import {
  ApiError,
  createTutorSource,
  ingestTutorAudio,
  ingestTutorConversation,
  ingestTutorPdf,
  ingestTutorSubtitle,
  ingestTutorTextFile,
  ingestTutorUrl,
  ingestTutorYoutube,
} from '../api/tutor'
import type { IngestFileInput, SourceDocument } from '../types'
import {
  activeFileSlot,
  ingestErrorFamily,
  ingestPendingLabel,
  ingestSubmitLabel,
  INGEST_FILE_SPECS,
  MISSING_FILE_MESSAGE,
  type ConversationInputMode,
  type IngestFileSlot,
  type SourceAddKind,
  type YoutubeInputMode,
  tutorIngestErrorMessage,
  validateHttpUrl,
  validateIngestFile,
} from '../utils/sourceIngestion'
import {
  fieldErrorsFromTutorApiBody,
  tutorNoteMetadata,
  tutorSaveErrorMessage,
} from '../utils/tutor'

export interface TutorSourceFieldErrors {
  title?: string
  content?: string
  url?: string
  video?: string
  file?: string
}

function isBlank(value: string): boolean {
  return value.trim() === ''
}

function filePayload(file: File, title: string, note: string): IngestFileInput {
  return {
    file,
    title: title.trim() || undefined,
    note: note.trim() || undefined,
    language: 'fr',
  }
}

/**
 * 同期の取り込み状態だけを持つ。失敗しても入力は捨てない。
 * 非同期ジョブの監視へ差し替えられるように、送信成否はこの hook に閉じる。
 */
export function useTutorSourceForm(onSaved: (source: SourceDocument) => void) {
  const [kind, setKindState] = useState<SourceAddKind>('manual')
  const [youtubeMode, setYoutubeModeState] = useState<YoutubeInputMode>('url')
  const [conversationMode, setConversationModeState] = useState<ConversationInputMode>('text-file')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [note, setNote] = useState('')
  const [url, setUrl] = useState('')
  const [video, setVideo] = useState('')
  const [files, setFiles] = useState<Partial<Record<IngestFileSlot, File>>>({})
  const [fieldErrors, setFieldErrors] = useState<TutorSourceFieldErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submittingRef = useRef(false)

  const slot = activeFileSlot(kind, youtubeMode, conversationMode)
  const file = slot ? files[slot] ?? null : null
  const fileSpec = slot ? INGEST_FILE_SPECS[slot] : null

  const setKind = useCallback((next: SourceAddKind) => {
    setKindState(next)
    setFieldErrors({})
    setSubmitError(null)
  }, [])

  const setYoutubeMode = useCallback((next: YoutubeInputMode) => {
    setYoutubeModeState(next)
    setFieldErrors({})
    setSubmitError(null)
  }, [])

  const setConversationMode = useCallback((next: ConversationInputMode) => {
    setConversationModeState(next)
    setFieldErrors({})
    setSubmitError(null)
  }, [])

  const setFile = useCallback((next: File | null) => {
    if (!slot) return
    setFiles(current => {
      const copy = { ...current }
      if (next) copy[slot] = next
      else delete copy[slot]
      return copy
    })
    setFieldErrors(current => ({ ...current, file: undefined }))
  }, [slot])

  const submit = useCallback(async () => {
    if (submittingRef.current) return

    if (kind === 'manual') {
      const errors: TutorSourceFieldErrors = {}
      if (isBlank(title)) errors.title = 'タイトルを入力してください'
      if (isBlank(content)) errors.content = 'フランス語の本文を入力してください'
      if (errors.title || errors.content) {
        setFieldErrors(errors)
        setSubmitError(null)
        return
      }

      submittingRef.current = true
      setIsSubmitting(true)
      setFieldErrors({})
      setSubmitError(null)
      try {
        const created = await createTutorSource({
          title: title.trim(),
          content: content.trim(),
          language: 'fr',
          metadata: tutorNoteMetadata(note),
        })
        onSaved(created)
      } catch (error) {
        if (error instanceof ApiError) {
          const fromBody = fieldErrorsFromTutorApiBody(error.body)
          if (fromBody.title || fromBody.content) setFieldErrors(fromBody)
        }
        setSubmitError(tutorSaveErrorMessage(error))
      } finally {
        submittingRef.current = false
        setIsSubmitting(false)
      }
      return
    }

    const family = ingestErrorFamily(kind, youtubeMode, conversationMode)
    const errors: TutorSourceFieldErrors = {}
    if (kind === 'url') {
      const urlError = validateHttpUrl(url)
      if (urlError) errors.url = urlError
    }
    if (kind === 'youtube' && youtubeMode === 'url' && isBlank(video)) {
      errors.video = 'YouTubeのURLまたは動画IDを入力してください'
    }
    if (slot && fileSpec) {
      if (!file) errors.file = MISSING_FILE_MESSAGE
      else {
        const problem = validateIngestFile(file, fileSpec)
        if (problem) errors.file = problem
      }
    }
    if (errors.url || errors.video || errors.file) {
      setFieldErrors(errors)
      setSubmitError(null)
      return
    }

    submittingRef.current = true
    setIsSubmitting(true)
    setFieldErrors({})
    setSubmitError(null)
    try {
      const payload = file ? filePayload(file, title, note) : null
      let created: SourceDocument
      if (kind === 'url') {
        created = await ingestTutorUrl({
          url: url.trim(),
          title: title.trim() || undefined,
          note: note.trim() || undefined,
          language: 'fr',
        })
      } else if (kind === 'pdf' && payload) {
        created = await ingestTutorPdf(payload)
      } else if (kind === 'youtube' && youtubeMode === 'url') {
        created = await ingestTutorYoutube({
          video: video.trim(),
          title: title.trim() || undefined,
          note: note.trim() || undefined,
          language: 'fr',
        })
      } else if (kind === 'youtube' && payload) {
        created = await ingestTutorSubtitle(payload)
      } else if (kind === 'audio' && payload) {
        created = await ingestTutorAudio(payload)
      } else if (kind === 'conversation' && conversationMode === 'log' && payload) {
        created = await ingestTutorConversation(payload)
      } else if (payload) {
        created = await ingestTutorTextFile(payload)
      } else {
        throw new Error('ingest input missing')
      }
      onSaved(created)
    } catch (error) {
      setSubmitError(
        family
          ? tutorIngestErrorMessage(error, family)
          : '取り込みに失敗しました。通信環境を確認して再度お試しください',
      )
    } finally {
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }, [
    kind,
    youtubeMode,
    conversationMode,
    title,
    content,
    note,
    url,
    video,
    slot,
    file,
    fileSpec,
    onSaved,
  ])

  return {
    kind,
    setKind,
    youtubeMode,
    setYoutubeMode,
    conversationMode,
    setConversationMode,
    title,
    setTitle,
    content,
    setContent,
    note,
    setNote,
    url,
    setUrl,
    video,
    setVideo,
    file,
    fileSpec,
    setFile,
    fieldErrors,
    submitError,
    isSubmitting,
    pendingLabel: ingestPendingLabel(kind, youtubeMode, conversationMode),
    submitLabel: ingestSubmitLabel(kind),
    submit,
  }
}

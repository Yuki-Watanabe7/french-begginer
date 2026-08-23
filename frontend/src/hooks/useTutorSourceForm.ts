import { useCallback, useRef, useState } from 'react'
import { ApiError, createTutorSource } from '../api/tutor'
import type { SourceDocument } from '../types'
import {
  fieldErrorsFromTutorApiBody,
  tutorNoteMetadata,
  tutorSaveErrorMessage,
} from '../utils/tutor'

export interface TutorSourceFieldErrors {
  title?: string
  content?: string
}

function isBlank(value: string): boolean {
  return value.trim() === ''
}

export function useTutorSourceForm(onSaved: (source: SourceDocument) => void) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [note, setNote] = useState('')
  const [fieldErrors, setFieldErrors] = useState<TutorSourceFieldErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submittingRef = useRef(false)

  const validate = useCallback((): TutorSourceFieldErrors => {
    const errors: TutorSourceFieldErrors = {}
    if (isBlank(title)) errors.title = 'タイトルを入力してください'
    if (isBlank(content)) errors.content = 'フランス語の本文を入力してください'
    return errors
  }, [title, content])

  const submit = useCallback(async () => {
    if (submittingRef.current) return

    const errors = validate()
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
        if (fromBody.title || fromBody.content) {
          setFieldErrors(fromBody)
        }
      }
      setSubmitError(tutorSaveErrorMessage(error))
    } finally {
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }, [title, content, note, validate, onSaved])

  return {
    title,
    setTitle,
    content,
    setContent,
    note,
    setNote,
    fieldErrors,
    submitError,
    isSubmitting,
    submit,
  }
}

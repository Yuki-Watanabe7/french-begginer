import { useState } from 'react'
import type { SourceDocument, TutorSessionKind } from '../types'
import { PracticeSessionFlow } from './PracticeSessionFlow'
import { QuizSettings } from './QuizSettings'
import { TutorSourceDetail } from './TutorSourceDetail'
import { TutorSourceForm } from './TutorSourceForm'
import { TutorSourceList } from './TutorSourceList'

type TutorView = 'list' | 'form' | 'detail' | 'practice-settings' | 'practice'

interface Props {
  onBack: () => void
}

export function TutorFlow({ onBack }: Props) {
  const [view, setView] = useState<TutorView>('list')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [savedSource, setSavedSource] = useState<SourceDocument | null>(null)
  const [justSaved, setJustSaved] = useState(false)
  const [practiceSourceId, setPracticeSourceId] = useState<string | undefined>(undefined)
  const [sessionKind, setSessionKind] = useState<TutorSessionKind>('practice')
  const [questionCount, setQuestionCount] = useState(5)

  const openList = () => {
    setJustSaved(false)
    setSavedSource(null)
    setSelectedId(null)
    setView('list')
  }

  const openForm = () => {
    setJustSaved(false)
    setSavedSource(null)
    setView('form')
  }

  const openDetail = (sourceId: string, source?: SourceDocument, saved = false) => {
    setSelectedId(sourceId)
    setSavedSource(source ?? null)
    setJustSaved(saved)
    setView('detail')
  }

  const openPracticeSettings = (sourceId?: string) => {
    setSessionKind('practice')
    setPracticeSourceId(sourceId)
    setView('practice-settings')
  }

  const openReviewSettings = () => {
    setSessionKind('review')
    setPracticeSourceId(undefined)
    setView('practice-settings')
  }

  const backFromPractice = () => {
    if (sessionKind === 'review') {
      setView('list')
      return
    }
    if (practiceSourceId && selectedId) {
      setView('detail')
      return
    }
    setView('list')
  }

  if (view === 'form') {
    return (
      <TutorSourceForm
        onBack={openList}
        onSaved={source => openDetail(source.id, source, true)}
      />
    )
  }

  if (view === 'detail' && selectedId) {
    return (
      <TutorSourceDetail
        sourceId={selectedId}
        initialSource={savedSource}
        justSaved={justSaved}
        onBackToList={openList}
        onAddAnother={openForm}
        onStartPractice={() => openPracticeSettings(selectedId)}
      />
    )
  }

  if (view === 'practice-settings') {
    return (
      <QuizSettings
        onStart={size => {
          setQuestionCount(size)
          setView('practice')
        }}
        onBack={backFromPractice}
      />
    )
  }

  if (view === 'practice') {
    return (
      <PracticeSessionFlow
        sourceId={sessionKind === 'review' ? undefined : practiceSourceId}
        questionCount={questionCount}
        kind={sessionKind}
        onExit={backFromPractice}
      />
    )
  }

  return (
    <TutorSourceList
      onSelect={sourceId => openDetail(sourceId)}
      onAdd={openForm}
      onBack={onBack}
      onStartPractice={() => openPracticeSettings()}
      onStartReview={openReviewSettings}
    />
  )
}

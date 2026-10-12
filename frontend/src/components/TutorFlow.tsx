import { useState } from 'react'
import type { SourceDocument, TutorSessionKind } from '../types'
import { DEFAULT_TODAY_QUESTION_COUNT } from '../utils/tutor'
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
  const [savedNotice, setSavedNotice] = useState('保存しました')
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

  const openDetail = (
    sourceId: string,
    source?: SourceDocument,
    saved = false,
    notice = '保存しました',
  ) => {
    setSelectedId(sourceId)
    setSavedSource(source ?? null)
    setJustSaved(saved)
    setSavedNotice(notice)
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

  const openTodaySession = () => {
    setSessionKind('today')
    setPracticeSourceId(undefined)
    setQuestionCount(DEFAULT_TODAY_QUESTION_COUNT)
    setView('practice')
  }

  const backFromPractice = () => {
    if (sessionKind === 'review' || sessionKind === 'today') {
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
        onSaved={source =>
          openDetail(
            source.id,
            source,
            true,
            source.source_type === 'manual_text' ? '保存しました' : '取り込みました',
          )
        }
      />
    )
  }

  if (view === 'detail' && selectedId) {
    return (
      <TutorSourceDetail
        sourceId={selectedId}
        initialSource={savedSource}
        justSaved={justSaved}
        savedNotice={savedNotice}
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
        sourceId={sessionKind === 'practice' ? practiceSourceId : undefined}
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
      onStartToday={openTodaySession}
    />
  )
}

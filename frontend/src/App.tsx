import { useState } from 'react'
import { ModeSelector } from './components/ModeSelector'
import { NounCategorySelector } from './components/NounCategorySelector'
import { NounGenderCard } from './components/NounGenderCard'
import { NounSessionResult } from './components/NounSessionResult'
import { QuizCard } from './components/QuizCard'
import { QuizSettings } from './components/QuizSettings'
import { SessionResult } from './components/SessionResult'
import { VerbGroupSelector } from './components/VerbGroupSelector'
import { useNounQuiz } from './hooks/useNounQuiz'
import { useQuiz } from './hooks/useQuiz'

type AppMode = 'mode-select' | 'verb' | 'noun'

export default function App() {
  const [appMode, setAppMode] = useState<AppMode>('mode-select')
  const verbQuiz = useQuiz()
  const nounQuiz = useNounQuiz()

  const handleSelectVerb = () => {
    setAppMode('verb')
  }

  const handleSelectNoun = () => {
    setAppMode('noun')
  }

  const handleBackToModeSelect = () => {
    if (appMode === 'verb') verbQuiz.backToSetup()
    if (appMode === 'noun') nounQuiz.backToSetup()
    setAppMode('mode-select')
  }

  const verbNextLabel = (() => {
    const { state } = verbQuiz
    if (state.phase !== 'result') return '次の問題 →'
    if (state.isReviewPhase) {
      return state.reviewQueue.length === 0 ? '結果を見る →' : '次の問題 →'
    }
    if (state.questionNum >= state.sessionTotal) {
      return state.wrongAnswers.length > 0 ? '復習へ →' : '結果を見る →'
    }
    return '次の問題 →'
  })()

  const nounNextLabel = (() => {
    const { state } = nounQuiz
    if (state.phase !== 'result') return '次の問題 →'
    if (state.isReviewPhase) {
      return state.reviewQueue.length === 0 ? '結果を見る →' : '次の問題 →'
    }
    if (state.questionNum >= state.sessionTotal) {
      return state.wrongAnswers.length > 0 ? '復習へ →' : '結果を見る →'
    }
    return '次の問題 →'
  })()

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <h1 style={styles.title}>フランス語練習</h1>
      </header>

      <main style={styles.main}>
        {appMode === 'mode-select' && (
          <ModeSelector onSelectVerb={handleSelectVerb} onSelectNoun={handleSelectNoun} />
        )}

        {/* 動詞活用練習 */}
        {appMode === 'verb' && verbQuiz.state.phase === 'setup' && (
          <VerbGroupSelector onSelect={verbQuiz.selectGroup} />
        )}
        {appMode === 'verb' && verbQuiz.state.phase === 'quiz-settings' && (
          <QuizSettings
            onStart={size => { void verbQuiz.startSession(size) }}
            onBack={verbQuiz.backToSetup}
          />
        )}
        {appMode === 'verb' && verbQuiz.state.phase === 'loading' && (
          <p style={styles.msg}>読み込み中...</p>
        )}
        {appMode === 'verb' && verbQuiz.state.phase === 'error' && (
          <div style={styles.errorBox}>
            <p>{verbQuiz.state.error}</p>
            <button style={styles.retryBtn} onClick={verbQuiz.retryLoad}>再試行</button>
          </div>
        )}
        {appMode === 'verb' &&
          (verbQuiz.state.phase === 'answering' || verbQuiz.state.phase === 'result') &&
          verbQuiz.state.question && (
            <QuizCard
              question={verbQuiz.state.question}
              input={verbQuiz.state.input}
              result={verbQuiz.state.result}
              inputRef={verbQuiz.inputRef}
              onInputChange={verbQuiz.setInput}
              onSubmit={verbQuiz.submit}
              onNext={() => { void verbQuiz.nextQuestion() }}
              questionNum={verbQuiz.state.questionNum}
              sessionTotal={verbQuiz.state.sessionTotal}
              isReviewPhase={verbQuiz.state.isReviewPhase}
              nextLabel={verbNextLabel}
            />
          )}
        {appMode === 'verb' && verbQuiz.state.phase === 'session-result' && (
          <SessionResult
            firstCorrectCount={verbQuiz.state.firstCorrectCount}
            reviewCorrectCount={verbQuiz.state.reviewCorrectCount}
            unresolvedCount={Math.max(0, verbQuiz.state.wrongAnswers.length - verbQuiz.state.reviewCorrectCount)}
            wrongAnswers={verbQuiz.state.wrongAnswers}
            normalSessionTotal={verbQuiz.state.normalSessionTotal}
            onRetry={() => { void verbQuiz.startNewSession() }}
            onBackToSetup={handleBackToModeSelect}
          />
        )}

        {/* 名詞の性クイズ */}
        {appMode === 'noun' && nounQuiz.state.phase === 'noun-filter' && (
          <NounCategorySelector
            onSelect={nounQuiz.selectFilter}
            onBack={handleBackToModeSelect}
          />
        )}
        {appMode === 'noun' && nounQuiz.state.phase === 'quiz-settings' && (
          <QuizSettings
            onStart={size => { void nounQuiz.startSession(size) }}
            onBack={nounQuiz.backToFilter}
          />
        )}
        {appMode === 'noun' && nounQuiz.state.phase === 'loading' && (
          <p style={styles.msg}>読み込み中...</p>
        )}
        {appMode === 'noun' && nounQuiz.state.phase === 'error' && (
          <div style={styles.errorBox}>
            <p>{nounQuiz.state.error}</p>
            <button style={styles.retryBtn} onClick={nounQuiz.retryLoad}>再試行</button>
          </div>
        )}
        {appMode === 'noun' &&
          (nounQuiz.state.phase === 'answering' || nounQuiz.state.phase === 'result') &&
          nounQuiz.state.question && (
            <NounGenderCard
              question={nounQuiz.state.question}
              result={nounQuiz.state.result}
              onAnswer={gender => { void nounQuiz.submit(gender) }}
              onNext={() => { void nounQuiz.nextQuestion() }}
              questionNum={nounQuiz.state.questionNum}
              sessionTotal={nounQuiz.state.sessionTotal}
              isReviewPhase={nounQuiz.state.isReviewPhase}
              nextLabel={nounNextLabel}
            />
          )}
        {appMode === 'noun' && nounQuiz.state.phase === 'session-result' && (
          <NounSessionResult
            firstCorrectCount={nounQuiz.state.firstCorrectCount}
            reviewCorrectCount={nounQuiz.state.reviewCorrectCount}
            unresolvedCount={Math.max(0, nounQuiz.state.wrongAnswers.length - nounQuiz.state.reviewCorrectCount)}
            wrongAnswers={nounQuiz.state.wrongAnswers}
            normalSessionTotal={nounQuiz.state.normalSessionTotal}
            onRetry={() => { void nounQuiz.startNewSession() }}
            onBackToSetup={handleBackToModeSelect}
          />
        )}
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100dvh',
    background: '#f0f4ff',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    padding: '16px 20px',
    background: '#1a56d6',
  },
  title: {
    margin: 0,
    color: '#fff',
    fontSize: 22,
    fontWeight: 700,
  },
  main: {
    flex: 1,
    padding: '24px 16px',
    maxWidth: 480,
    width: '100%',
    margin: '0 auto',
    boxSizing: 'border-box',
  },
  msg: {
    textAlign: 'center',
    color: '#666',
    fontSize: 16,
    marginTop: 40,
  },
  errorBox: {
    textAlign: 'center',
    padding: 24,
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
  },
  retryBtn: {
    marginTop: 12,
    padding: '10px 24px',
    fontSize: 16,
    borderRadius: 10,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
  },
}

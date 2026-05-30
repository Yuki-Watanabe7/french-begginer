import { QuizCard } from './components/QuizCard'
import { SessionResult } from './components/SessionResult'
import { VerbGroupSelector } from './components/VerbGroupSelector'
import { useQuiz } from './hooks/useQuiz'

export default function App() {
  const { state, inputRef, submit, setInput, nextQuestion, startNewSession, startReview, retryLoad, startSession } = useQuiz()

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <h1 style={styles.title}>🇫🇷 動詞活用練習</h1>
      </header>

      <main style={styles.main}>
        {state.phase === 'setup' && (
          <VerbGroupSelector onStart={group => { void startSession(group) }} />
        )}

        {state.phase === 'loading' && <p style={styles.msg}>読み込み中...</p>}

        {state.phase === 'error' && (
          <div style={styles.errorBox}>
            <p>{state.error}</p>
            <button style={styles.retryBtn} onClick={retryLoad}>再試行</button>
          </div>
        )}

        {(state.phase === 'answering' || state.phase === 'result') && state.question && (
          <QuizCard
            question={state.question}
            input={state.input}
            result={state.result}
            inputRef={inputRef}
            onInputChange={setInput}
            onSubmit={submit}
            onNext={() => { void nextQuestion() }}
            questionNum={state.questionNum}
            sessionTotal={state.sessionTotal}
          />
        )}

        {state.phase === 'session-result' && (
          <SessionResult
            correctCount={state.correctCount}
            wrongAnswers={state.wrongAnswers}
            sessionTotal={state.sessionTotal}
            onRetry={() => { void startNewSession() }}
            onReview={startReview}
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

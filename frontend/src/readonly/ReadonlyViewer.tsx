import { useEffect, useState } from 'react'
import { loadSnapshot, SnapshotFormatError } from './snapshot'
import type { PublicCard, PublicSnapshot } from './snapshot'

const typeLabels: Record<PublicCard['item_type'], string> = {
  vocabulary: '単語', expression: '表現', grammar: '文法', conjugation: '活用',
}

type LoadState =
  | { phase: 'loading' }
  | { phase: 'ready'; snapshot: PublicSnapshot }
  | { phase: 'error'; message: string }

export default function ReadonlyViewer() {
  const [state, setState] = useState<LoadState>({ phase: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10_000)
    let active = true
    setState({ phase: 'loading' })
    loadSnapshot(controller.signal).then(snapshot => {
      if (active) setState({ phase: 'ready', snapshot })
    }).catch((error: unknown) => {
      if (active) setState({
        phase: 'error',
        message: error instanceof SnapshotFormatError
          ? '教材ファイルの形式が正しくありません。公開元での確認が必要です。'
          : '教材を読み込めませんでした。通信状況を確認して、もう一度お試しください。',
      })
    }).finally(() => window.clearTimeout(timeout))
    return () => {
      active = false
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [attempt])

  return (
    <div>
      <header style={styles.header}>
        <p style={styles.brand}>フランス語練習</p>
        <h1 style={styles.title}>公開教材</h1>
        <p style={styles.subtitle}>カードを読んで、フランス語にふれる。</p>
      </header>
      <main style={styles.main}>
        <p style={styles.note}>閲覧専用です。答えの開閉や学習の記録は保存されません。</p>
        {state.phase === 'loading' && <p role="status">教材を読み込んでいます…</p>}
        {state.phase === 'error' && (
          <section style={styles.card} aria-label="読み込みエラー">
            <p role="alert">{state.message}</p>
            <button style={styles.button} onClick={() => setAttempt(value => value + 1)}>再読み込み</button>
          </section>
        )}
        {state.phase === 'ready' && (
          <>
            <section style={styles.metadata} aria-label="教材の情報">
              <p style={styles.metaLine}>
                教材の書き出し日時：<time dateTime={state.snapshot.generated_at}>
                  {state.snapshot.generated_at.replace('T', ' ').replace('Z', ' UTC')}
                </time>
              </p>
              <p style={styles.metaLine}>書き出した時点の教材です。現在の学習状況とは連動しません。</p>
              <p style={styles.metaLine}>{state.snapshot.cards.length}枚のカード · 答えをタップして確認</p>
            </section>
            <ol style={styles.list} aria-label="教材カード">
              {state.snapshot.cards.map((card, index) => (
                <li key={card.card_id} style={styles.card}>
                  <p style={styles.label}>{index + 1} · {typeLabels[card.item_type]}{card.level && ` · ${card.level}`}</p>
                  <h2 lang="fr" style={styles.question}>{card.canonical_form}</h2>
                  <details>
                    <summary style={styles.summary}>答えを見る・閉じる</summary>
                    <div style={styles.answer}>
                      <p style={styles.meaning}>{card.meaning_ja}</p>
                      {card.explanation_ja && <p style={styles.explanation}>{card.explanation_ja}</p>}
                    </div>
                  </details>
                </li>
              ))}
            </ol>
          </>
        )}
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  header: { background: '#1a56d6', color: '#fff', padding: '28px 20px' },
  brand: { margin: '0 0 8px', fontSize: 14 },
  title: { margin: 0, fontSize: 28 },
  subtitle: { margin: '10px 0 0', fontSize: 16 },
  main: { boxSizing: 'border-box', maxWidth: 560, padding: '20px 16px 40px', margin: '0 auto', overflowWrap: 'anywhere' },
  note: { margin: '0 0 20px', fontSize: 14, lineHeight: 1.7, color: '#42526e' },
  metadata: { marginBottom: 24, fontSize: 14, lineHeight: 1.7 },
  metaLine: { margin: '6px 0' },
  list: { listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 16 },
  card: { minWidth: 0, background: '#fff', borderRadius: 16, padding: 20, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' },
  label: { color: '#42526e', fontSize: 14, margin: '0 0 12px' },
  question: { fontSize: 24, lineHeight: 1.5, margin: '0 0 16px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
  summary: { padding: '12px 4px', minHeight: 24, color: '#1749ae', cursor: 'pointer', fontSize: 16, fontWeight: 600 },
  answer: { borderTop: '1px solid #e1e7f0', marginTop: 8, paddingTop: 8, whiteSpace: 'pre-wrap' },
  meaning: { fontSize: 18, lineHeight: 1.7, margin: '8px 0' },
  explanation: { fontSize: 16, lineHeight: 1.8, margin: '12px 0 0', color: '#42526e' },
  button: { fontSize: 16, padding: '12px 20px', border: 0, borderRadius: 10, background: '#1a56d6', color: '#fff', cursor: 'pointer', minHeight: 48 },
}

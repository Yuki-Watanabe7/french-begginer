interface Props {
  onSelectVerb: () => void
  onSelectNoun: () => void
  onSelectNounArticle: () => void
}

export function ModeSelector({ onSelectVerb, onSelectNoun, onSelectNounArticle }: Props) {
  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>練習モードを選択</h2>
      <p style={styles.sub}>学習したいモードを選んでください</p>
      <div style={styles.grid}>
        <button style={styles.card} onClick={onSelectVerb}>
          <span style={styles.label}>動詞活用練習</span>
          <span style={styles.desc}>直説法現在形の活用を練習する</span>
        </button>
        <button style={styles.card} onClick={onSelectNoun}>
          <span style={styles.label}>名詞の性クイズ</span>
          <span style={styles.desc}>名詞が男性名詞か女性名詞かを答える</span>
        </button>
        <button style={styles.card} onClick={onSelectNounArticle}>
          <span style={styles.label}>冠詞付き名詞</span>
          <span style={styles.desc}>日本語訳から un / une + 名詞を入力する</span>
        </button>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    textAlign: 'center',
  },
  heading: {
    fontSize: 22,
    fontWeight: 700,
    color: '#1a1a2e',
    marginBottom: 8,
  },
  sub: {
    color: '#666',
    fontSize: 14,
    marginBottom: 24,
  },
  grid: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 4,
    padding: '16px 20px',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'border-color 0.15s',
  },
  label: {
    fontSize: 17,
    fontWeight: 700,
    color: '#1a56d6',
  },
  desc: {
    fontSize: 13,
    color: '#555',
  },
}

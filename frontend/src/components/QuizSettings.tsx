interface Props {
  onStart: (sessionSize: number) => void
  onBack: () => void
}

interface SizeOption {
  value: number
  label: string
  description: string
}

const SIZE_OPTIONS: SizeOption[] = [
  { value: 5, label: '5問', description: '短時間で手軽に練習' },
  { value: 10, label: '10問', description: '標準的な練習量（デフォルト）' },
  { value: 20, label: '20問', description: 'じっくり集中して練習' },
]

export function QuizSettings({ onStart, onBack }: Props) {
  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>出題数を選択</h2>
      <p style={styles.sub}>1セッションの問題数を選んでください</p>
      <div style={styles.grid}>
        {SIZE_OPTIONS.map(opt => (
          <button key={opt.value} style={styles.card} onClick={() => onStart(opt.value)}>
            <span style={styles.label}>{opt.label}</span>
            <span style={styles.desc}>{opt.description}</span>
          </button>
        ))}
      </div>
      <button style={styles.backBtn} onClick={onBack}>戻る</button>
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
    marginBottom: 16,
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
  backBtn: {
    fontSize: 15,
    fontWeight: 500,
    padding: '10px 24px',
    borderRadius: 12,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#666',
    cursor: 'pointer',
  },
}

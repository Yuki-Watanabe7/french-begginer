import type { VerbGroup } from '../types'

interface Props {
  onStart: (group: VerbGroup) => void
}

const GROUPS: { value: VerbGroup; label: string; description: string }[] = [
  { value: 'all', label: '全動詞', description: 'すべてのグループから出題' },
  { value: 'er', label: '-er 動詞', description: 'parler, aimer, travailler など' },
  { value: 'ir', label: '-ir 動詞', description: 'finir, choisir など' },
  { value: 'irregular', label: '不規則動詞', description: 'être, avoir, aller, faire など' },
]

export function VerbGroupSelector({ onStart }: Props) {
  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>学習モードを選択</h2>
      <div style={styles.list}>
        {GROUPS.map(g => (
          <button key={g.value} style={styles.card} onClick={() => onStart(g.value)}>
            <span style={styles.label}>{g.label}</span>
            <span style={styles.desc}>{g.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  heading: {
    margin: 0,
    fontSize: 20,
    fontWeight: 700,
    color: '#1a56d6',
    textAlign: 'center',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    marginTop: 8,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    padding: '16px 20px',
    background: '#fff',
    border: '2px solid #e0e8ff',
    borderRadius: 16,
    cursor: 'pointer',
    textAlign: 'left',
    width: '100%',
    gap: 4,
    boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
  },
  label: {
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a1a',
  },
  desc: {
    fontSize: 13,
    color: '#666',
  },
}

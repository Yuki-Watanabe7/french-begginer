import type { VerbGroup } from '../types'

interface Props {
  onSelect: (group: VerbGroup) => void
}

interface GroupOption {
  value: VerbGroup
  label: string
  description: string
}

const GROUP_OPTIONS: GroupOption[] = [
  { value: 'all', label: '全動詞', description: 'すべての動詞から出題' },
  { value: 'er', label: '-er 動詞', description: 'parler, aimer など規則動詞' },
  { value: 'ir', label: '-ir 動詞', description: 'finir, choisir など規則動詞' },
  { value: 'irregular', label: '不規則動詞', description: 'être, avoir, aller, faire' },
]

export function VerbGroupSelector({ onSelect }: Props) {
  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>学習モードを選択</h2>
      <p style={styles.sub}>出題したい動詞グループを選んでください</p>
      <div style={styles.grid}>
        {GROUP_OPTIONS.map(opt => (
          <button key={opt.value} style={styles.card} onClick={() => onSelect(opt.value)}>
            <span style={styles.label}>{opt.label}</span>
            <span style={styles.desc}>{opt.description}</span>
          </button>
        ))}
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

import type { NounFilter } from '../types'

interface Props {
  onSelect: (filter: NounFilter) => void
  onBack: () => void
}

interface FilterOption {
  label: string
  description: string
  filter: NounFilter
}

const FILTER_OPTIONS: FilterOption[] = [
  { label: '全名詞', description: 'すべての名詞から出題', filter: {} },
  { label: '基本名詞', description: '初級者向けの基本語彙', filter: { level: 'basic' } },
  { label: '食べ物', description: '食べ物・飲み物', filter: { category: 'food' } },
  { label: '場所', description: '場所・建物', filter: { category: 'place' } },
  { label: '家・生活', description: '家・生活用品', filter: { category: 'home' } },
  { label: '人・家族', description: '人物・家族・職業', filter: { category: 'person' } },
  { label: '時間', description: '時間・曜日・月', filter: { category: 'time' } },
  { label: '学校', description: '学校・勉強', filter: { category: 'school' } },
  { label: '自然', description: '自然・動植物', filter: { category: 'nature' } },
  { label: '抽象語', description: '抽象的な概念', filter: { category: 'abstract' } },
]

export function NounCategorySelector({ onSelect, onBack }: Props) {
  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>出題範囲を選択</h2>
      <p style={styles.sub}>練習したい名詞のカテゴリを選んでください</p>
      <div style={styles.grid}>
        {FILTER_OPTIONS.map(opt => (
          <button
            key={opt.label}
            style={styles.card}
            onClick={() => onSelect(opt.filter)}
          >
            <span style={styles.label}>{opt.label}</span>
            <span style={styles.desc}>{opt.description}</span>
          </button>
        ))}
      </div>
      <button style={styles.backBtn} onClick={onBack}>モード選択に戻る</button>
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
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
    marginBottom: 16,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 4,
    padding: '14px 16px',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'border-color 0.15s',
  },
  label: {
    fontSize: 16,
    fontWeight: 700,
    color: '#1a56d6',
  },
  desc: {
    fontSize: 12,
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

import { useState } from 'react'
import type { VerbFilter, VerbGroup, VerbLevel, VerbPattern } from '../types'

interface Props {
  onSelect: (filter: VerbFilter) => void
}

const GROUP_OPTIONS: { value: VerbGroup; label: string; description: string }[] = [
  { value: 'all', label: '全動詞', description: 'すべての動詞から出題' },
  { value: 'er', label: '-er 動詞', description: 'parler, aimer など' },
  { value: 'ir', label: '-ir 動詞', description: 'finir, choisir など' },
  { value: 'irregular', label: '不規則動詞', description: 'être, avoir など' },
]

const LEVEL_OPTIONS: { value: VerbLevel | undefined; label: string; description: string }[] = [
  { value: undefined, label: 'すべて', description: '難易度を絞らない' },
  { value: 'basic', label: '基本', description: '最重要動詞' },
  { value: 'standard', label: '標準', description: '標準レベル' },
  { value: 'challenge', label: '応用', description: '発展的な動詞' },
]

const PATTERN_OPTIONS: { value: VerbPattern | undefined; label: string; description: string }[] = [
  { value: undefined, label: 'すべて', description: 'パターンを絞らない' },
  { value: 'regular', label: '規則活用', description: '規則どおりの活用' },
  { value: 'stem_change', label: '語幹変化', description: '語幹が変わる動詞' },
  { value: 'spelling_change', label: '綴り変化', description: '綴りが変わる動詞' },
  { value: 'irregular', label: '不規則', description: '不規則な活用' },
]

export function VerbGroupSelector({ onSelect }: Props) {
  const [group, setGroup] = useState<VerbGroup>('all')
  const [level, setLevel] = useState<VerbLevel | undefined>(undefined)
  const [pattern, setPattern] = useState<VerbPattern | undefined>(undefined)

  const handleSubmit = () => {
    onSelect({ group, level, pattern })
  }

  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>学習モードを選択</h2>
      <p style={styles.sub}>出題したい動詞の範囲を選んでください</p>

      <div style={styles.section}>
        <p style={styles.sectionLabel}>動詞グループ</p>
        <div style={styles.chipGrid}>
          {GROUP_OPTIONS.map(opt => (
            <button
              key={opt.value}
              style={{ ...styles.chip, ...(group === opt.value ? styles.chipSelected : {}) }}
              onClick={() => setGroup(opt.value)}
              aria-pressed={group === opt.value}
            >
              <span style={styles.chipLabel}>{opt.label}</span>
              <span style={styles.chipDesc}>{opt.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={styles.section}>
        <p style={styles.sectionLabel}>
          難易度
          <span style={styles.optional}>（任意）</span>
        </p>
        <div style={styles.chipGridWrap}>
          {LEVEL_OPTIONS.map(opt => (
            <button
              key={String(opt.value)}
              style={{ ...styles.chip, ...(level === opt.value ? styles.chipSelected : {}) }}
              onClick={() => setLevel(opt.value)}
              aria-pressed={level === opt.value}
            >
              <span style={styles.chipLabel}>{opt.label}</span>
              <span style={styles.chipDesc}>{opt.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={styles.section}>
        <p style={styles.sectionLabel}>
          活用パターン
          <span style={styles.optional}>（任意）</span>
        </p>
        <div style={styles.chipGridWrap}>
          {PATTERN_OPTIONS.map(opt => (
            <button
              key={String(opt.value)}
              style={{ ...styles.chip, ...(pattern === opt.value ? styles.chipSelected : {}) }}
              onClick={() => setPattern(opt.value)}
              aria-pressed={pattern === opt.value}
            >
              <span style={styles.chipLabel}>{opt.label}</span>
              <span style={styles.chipDesc}>{opt.description}</span>
            </button>
          ))}
        </div>
      </div>

      <button style={styles.nextBtn} onClick={handleSubmit}>
        次へ →
      </button>
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
  section: {
    marginBottom: 20,
    textAlign: 'left',
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: 700,
    color: '#444',
    marginBottom: 8,
    marginTop: 0,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  optional: {
    fontWeight: 400,
    color: '#888',
    fontSize: 12,
    marginLeft: 4,
    textTransform: 'none' as const,
    letterSpacing: 0,
  },
  chipGrid: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  chipGridWrap: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 8,
  },
  chip: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'flex-start',
    gap: 2,
    padding: '10px 14px',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 12,
    cursor: 'pointer',
    textAlign: 'left' as const,
    transition: 'border-color 0.15s, background 0.15s',
  },
  chipSelected: {
    background: '#eff4ff',
    borderColor: '#1a56d6',
  },
  chipLabel: {
    fontSize: 15,
    fontWeight: 700,
    color: '#1a56d6',
  },
  chipDesc: {
    fontSize: 11,
    color: '#666',
  },
  nextBtn: {
    marginTop: 8,
    width: '100%',
    padding: '14px 0',
    fontSize: 17,
    fontWeight: 700,
    borderRadius: 14,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
  },
}

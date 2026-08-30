interface Props {
  options: string[]
  selectedIndices: number[]
  disabled: boolean
  onChange: (indices: number[]) => void
}

export function PracticeReconstructionBoard({
  options,
  selectedIndices,
  disabled,
  onChange,
}: Props) {
  const used = new Set(selectedIndices)
  const remaining = options
    .map((token, index) => ({ token, index }))
    .filter(row => !used.has(row.index))

  const add = (index: number) => {
    if (disabled || used.has(index)) return
    onChange([...selectedIndices, index])
  }

  const removeAt = (assembledIndex: number) => {
    if (disabled) return
    onChange(selectedIndices.filter((_, i) => i !== assembledIndex))
  }

  const clear = () => {
    if (disabled) return
    onChange([])
  }

  return (
    <div style={styles.wrap}>
      <div style={styles.assembled} aria-label="並べた語">
        {selectedIndices.length === 0 ? (
          <span style={styles.placeholder}>語をタップして文を組み立ててください</span>
        ) : (
          selectedIndices.map((optionIndex, assembledIndex) => (
            <button
              key={`sel-${optionIndex}-${assembledIndex}`}
              type="button"
              style={styles.selectedToken}
              disabled={disabled}
              onClick={() => removeAt(assembledIndex)}
            >
              {options[optionIndex]}
            </button>
          ))
        )}
      </div>
      <div style={styles.pool} aria-label="使える語">
        {remaining.map(row => (
          <button
            key={`pool-${row.index}`}
            type="button"
            style={styles.poolToken}
            disabled={disabled}
            onClick={() => add(row.index)}
          >
            {row.token}
          </button>
        ))}
      </div>
      {selectedIndices.length > 0 && !disabled && (
        <button type="button" style={styles.clearBtn} onClick={clear}>
          並べた語をクリア
        </button>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    width: '100%',
  },
  assembled: {
    minHeight: 56,
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    alignItems: 'center',
    background: '#f8fafc',
    border: '2px dashed #cbd5e1',
    borderRadius: 12,
    padding: 12,
    width: '100%',
    boxSizing: 'border-box',
  },
  placeholder: {
    color: '#94a3b8',
    fontSize: 14,
    lineHeight: 1.5,
  },
  pool: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    width: '100%',
  },
  poolToken: {
    fontSize: 16,
    fontWeight: 700,
    minHeight: 44,
    padding: '10px 14px',
    borderRadius: 12,
    border: '2px solid #1a56d6',
    background: '#fff',
    color: '#1a56d6',
    cursor: 'pointer',
    overflowWrap: 'anywhere',
  },
  selectedToken: {
    fontSize: 16,
    fontWeight: 700,
    minHeight: 44,
    padding: '10px 14px',
    borderRadius: 12,
    border: '2px solid #1a56d6',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    overflowWrap: 'anywhere',
  },
  clearBtn: {
    fontSize: 14,
    fontWeight: 600,
    minHeight: 44,
    padding: '8px 12px',
    borderRadius: 10,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#555',
    cursor: 'pointer',
    alignSelf: 'flex-start',
  },
}

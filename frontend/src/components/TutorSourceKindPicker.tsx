interface Option<T extends string> {
  id: T
  label: string
}

interface Props<T extends string> {
  legend: string
  name: string
  value: T
  options: readonly Option<T>[]
  disabled?: boolean
  onChange: (value: T) => void
}

export function TutorSourceKindPicker<T extends string>({
  legend,
  name,
  value,
  options,
  disabled = false,
  onChange,
}: Props<T>) {
  const legendId = `${name}-legend`
  return (
    <div style={styles.group}>
      <div id={legendId} style={styles.legend}>
        {legend}
      </div>
      <div
        role="radiogroup"
        aria-labelledby={legendId}
        style={styles.options}
      >
        {options.map(option => {
          const selected = option.id === value
          return (
            <label
              key={option.id}
              style={{
                ...styles.option,
                ...(selected ? styles.optionSelected : {}),
                ...(disabled ? styles.optionDisabled : {}),
              }}
            >
              <input
                type="radio"
                name={name}
                value={option.id}
                checked={selected}
                disabled={disabled}
                onChange={() => onChange(option.id)}
                style={styles.radio}
              />
              <span style={styles.optionLabel}>{option.label}</span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  group: {
    margin: '0 0 16px',
    minWidth: 0,
    maxWidth: '100%',
  },
  legend: {
    fontSize: 13,
    fontWeight: 700,
    color: '#444',
    marginBottom: 8,
  },
  options: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    minWidth: 0,
    maxWidth: '100%',
  },
  option: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    flex: '1 1 140px',
    maxWidth: '100%',
    minWidth: 0,
    boxSizing: 'border-box',
    minHeight: 44,
    padding: '10px 12px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    background: '#fff',
    cursor: 'pointer',
  },
  optionSelected: {
    border: '2px solid #1a56d6',
    background: '#eef2ff',
  },
  optionDisabled: {
    opacity: 0.7,
    cursor: 'not-allowed',
  },
  radio: {
    width: 18,
    height: 18,
    marginTop: 1,
    flex: '0 0 auto',
  },
  optionLabel: {
    fontSize: 14,
    fontWeight: 700,
    color: '#1a1a2e',
    lineHeight: 1.4,
    overflowWrap: 'anywhere',
  },
}

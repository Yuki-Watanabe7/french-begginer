import { formatFileSize } from '../utils/sourceIngestion'

interface Props {
  inputId: string
  accept: string
  file: File | null
  error?: string
  disabled?: boolean
  onFile: (file: File | null) => void
}

export function TutorSourceFileField({
  inputId,
  accept,
  file,
  error,
  disabled = false,
  onFile,
}: Props) {
  const errorId = `${inputId}-error`

  return (
    <div style={styles.wrap}>
      <label htmlFor={inputId} style={styles.label}>
        ファイル
        <span style={styles.required}>必須</span>
      </label>
      <input
        id={inputId}
        style={{
          ...styles.input,
          ...(error ? styles.inputInvalid : {}),
        }}
        type="file"
        accept={accept}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        onClick={event => {
          event.currentTarget.value = ''
        }}
        onChange={event => {
          onFile(event.currentTarget.files?.[0] ?? null)
        }}
      />
      {file && (
        <p style={styles.meta}>
          <span style={styles.name}>{file.name}</span>
          <span style={styles.size}>{formatFileSize(file.size)}</span>
        </p>
      )}
      {error && (
        <p id={errorId} style={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    maxWidth: '100%',
    marginBottom: 16,
  },
  label: {
    fontSize: 13,
    fontWeight: 700,
    color: '#444',
    marginBottom: 8,
  },
  required: {
    marginLeft: 8,
    fontSize: 11,
    fontWeight: 700,
    color: '#dc2626',
    background: '#fee2e2',
    borderRadius: 6,
    padding: '2px 6px',
  },
  input: {
    fontSize: 16,
    width: '100%',
    maxWidth: '100%',
    minHeight: 44,
    boxSizing: 'border-box',
  },
  inputInvalid: {
    outline: '2px solid #dc2626',
  },
  meta: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    margin: '8px 0 0',
    minWidth: 0,
    maxWidth: '100%',
  },
  name: {
    fontSize: 14,
    fontWeight: 700,
    color: '#1a1a2e',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
    minWidth: 0,
    maxWidth: '100%',
  },
  size: {
    fontSize: 13,
    color: '#666',
  },
  error: {
    color: '#dc2626',
    fontSize: 13,
    margin: '8px 0 0',
  },
}

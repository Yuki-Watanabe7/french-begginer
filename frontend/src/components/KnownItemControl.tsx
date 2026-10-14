import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

interface Props {
  explicitKnown: boolean
  busy: boolean
  error: string | null
  onMark: () => void
  onUndo: () => void
}

export function KnownItemControl({
  explicitKnown,
  busy,
  error,
  onMark,
  onUndo,
}: Props) {
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (explicitKnown) setConfirming(false)
  }, [explicitKnown])

  return (
    <div style={styles.wrap}>
      {explicitKnown ? (
        <>
          <p style={styles.known} role="status">
            知っているので、新しい学習には出しません
          </p>
          <button type="button" style={styles.undoBtn} disabled={busy} onClick={onUndo}>
            元に戻す
          </button>
        </>
      ) : confirming ? (
        <>
          <p style={styles.confirm}>
            新しい学習から外します。復習の予定は残ります。あとから戻せます。
          </p>
          <div style={styles.row}>
            <button type="button" style={styles.markBtn} disabled={busy} onClick={onMark}>
              外す
            </button>
            <button
              type="button"
              style={styles.cancelBtn}
              disabled={busy}
              onClick={() => setConfirming(false)}
            >
              やめる
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          style={styles.askBtn}
          disabled={busy}
          onClick={() => setConfirming(true)}
        >
          これは知っている
        </button>
      )}
      {error && (
        <p style={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

const styles: Record<string, CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  known: {
    margin: 0,
    fontSize: 14,
    lineHeight: 1.5,
    color: '#065f46',
    background: '#d1fae5',
    borderRadius: 10,
    padding: '10px 12px',
  },
  confirm: {
    margin: 0,
    fontSize: 14,
    lineHeight: 1.5,
    color: '#1a1a2e',
  },
  row: {
    display: 'flex',
    gap: 8,
  },
  askBtn: {
    minHeight: 44,
    fontSize: 15,
    fontWeight: 700,
    padding: '10px 12px',
    borderRadius: 12,
    border: '1px solid #bfdbfe',
    background: '#eff6ff',
    color: '#1a56d6',
    cursor: 'pointer',
  },
  markBtn: {
    flex: 1,
    minHeight: 44,
    fontSize: 15,
    fontWeight: 700,
    borderRadius: 12,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
  },
  cancelBtn: {
    flex: 1,
    minHeight: 44,
    fontSize: 15,
    fontWeight: 700,
    borderRadius: 12,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#444',
    cursor: 'pointer',
  },
  undoBtn: {
    minHeight: 44,
    fontSize: 15,
    fontWeight: 700,
    padding: '10px 12px',
    borderRadius: 12,
    border: '1px solid #6ee7b7',
    background: '#fff',
    color: '#065f46',
    cursor: 'pointer',
  },
  error: {
    margin: 0,
    color: '#b91c1c',
    fontSize: 13,
    lineHeight: 1.5,
  },
}

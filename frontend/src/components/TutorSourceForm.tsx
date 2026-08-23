import { useTutorSourceForm } from '../hooks/useTutorSourceForm'
import { tutorNoteFromMetadata } from '../utils/tutor'
import type { SourceDocument } from '../types'

interface Props {
  onBack: () => void
}

export function TutorSourceForm({ onBack }: Props) {
  const form = useTutorSourceForm()

  if (form.saved) {
    return (
      <SavedSourceView
        source={form.saved}
        onAddAnother={form.resetForAnother}
        onBack={onBack}
      />
    )
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    void form.submit()
  }

  return (
    <form style={styles.container} onSubmit={handleSubmit} noValidate>
      <h2 style={styles.heading}>フランス語テキストを保存</h2>
      <p style={styles.sub}>読んだ・見聞きした文章を貼り付けて、あとから教材にできます</p>

      <label htmlFor="tutor-source-title" style={styles.label}>
        タイトル
        <span style={styles.required}>必須</span>
      </label>
      <input
        id="tutor-source-title"
        style={{
          ...styles.input,
          ...(form.fieldErrors.title ? styles.inputInvalid : {}),
        }}
        type="text"
        value={form.title}
        onChange={e => form.setTitle(e.target.value)}
        placeholder="記事のタイトル、会話メモなど"
        aria-required="true"
        aria-invalid={Boolean(form.fieldErrors.title)}
        aria-describedby={form.fieldErrors.title ? 'tutor-source-title-error' : undefined}
        disabled={form.isSubmitting}
        autoComplete="off"
      />
      {form.fieldErrors.title && (
        <p id="tutor-source-title-error" style={styles.fieldError} role="alert">
          {form.fieldErrors.title}
        </p>
      )}

      <label htmlFor="tutor-source-content" style={styles.label}>
        本文
        <span style={styles.required}>必須</span>
      </label>
      <textarea
        id="tutor-source-content"
        style={{
          ...styles.textarea,
          ...(form.fieldErrors.content ? styles.inputInvalid : {}),
        }}
        value={form.content}
        onChange={e => form.setContent(e.target.value)}
        placeholder="フランス語の文章を貼り付けてください"
        aria-required="true"
        aria-invalid={Boolean(form.fieldErrors.content)}
        aria-describedby={form.fieldErrors.content ? 'tutor-source-content-error' : undefined}
        disabled={form.isSubmitting}
        lang="fr"
        spellCheck={false}
      />
      {form.fieldErrors.content && (
        <p id="tutor-source-content-error" style={styles.fieldError} role="alert">
          {form.fieldErrors.content}
        </p>
      )}

      <label htmlFor="tutor-source-note" style={styles.label}>
        メモ
        <span style={styles.optional}>任意</span>
      </label>
      <textarea
        id="tutor-source-note"
        style={styles.note}
        value={form.note}
        onChange={e => form.setNote(e.target.value)}
        placeholder="どこで読んだか、難しかったところなど"
        disabled={form.isSubmitting}
      />

      {form.submitError && (
        <p style={styles.submitError} role="alert">
          {form.submitError}
        </p>
      )}

      <button
        type="submit"
        style={{
          ...styles.primaryBtn,
          ...(form.isSubmitting ? styles.primaryBtnDisabled : {}),
        }}
        disabled={form.isSubmitting}
      >
        {form.isSubmitting ? '保存中...' : '保存する'}
      </button>
      <button type="button" style={styles.backBtn} onClick={onBack} disabled={form.isSubmitting}>
        モード選択に戻る
      </button>
    </form>
  )
}

function SavedSourceView({
  source,
  onAddAnother,
  onBack,
}: {
  source: SourceDocument
  onAddAnother: () => void
  onBack: () => void
}) {
  const note = tutorNoteFromMetadata(source.metadata)

  return (
    <div style={styles.container}>
      <div style={styles.successBanner} role="status">
        保存しました
      </div>
      <h2 style={styles.savedTitle}>{source.title}</h2>
      {note && <p style={styles.savedNote}>{note}</p>}
      <div style={styles.savedContent}>{source.content}</div>
      <button type="button" style={styles.primaryBtn} onClick={onAddAnother}>
        続けてテキストを追加
      </button>
      <button type="button" style={styles.backBtn} onClick={onBack}>
        モード選択に戻る
      </button>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    textAlign: 'left',
  },
  heading: {
    fontSize: 22,
    fontWeight: 700,
    color: '#1a1a2e',
    marginBottom: 8,
    textAlign: 'center',
  },
  sub: {
    color: '#666',
    fontSize: 14,
    marginBottom: 24,
    textAlign: 'center',
    lineHeight: 1.5,
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
  optional: {
    marginLeft: 8,
    fontSize: 11,
    fontWeight: 500,
    color: '#666',
    background: '#f3f4f6',
    borderRadius: 6,
    padding: '2px 6px',
  },
  input: {
    fontSize: 16,
    padding: '12px 14px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    marginBottom: 16,
  },
  textarea: {
    fontSize: 16,
    padding: '12px 14px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    minHeight: '40vh',
    resize: 'vertical',
    lineHeight: 1.6,
    marginBottom: 16,
  },
  note: {
    fontSize: 16,
    padding: '12px 14px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    minHeight: 88,
    resize: 'vertical',
    lineHeight: 1.5,
    marginBottom: 16,
  },
  inputInvalid: {
    borderColor: '#dc2626',
    marginBottom: 8,
  },
  fieldError: {
    color: '#dc2626',
    fontSize: 13,
    margin: '0 0 16px',
  },
  submitError: {
    color: '#dc2626',
    fontSize: 14,
    background: '#fee2e2',
    borderRadius: 10,
    padding: '10px 12px',
    margin: '0 0 16px',
  },
  primaryBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '14px 0',
    borderRadius: 14,
    border: 'none',
    background: '#1a56d6',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  primaryBtnDisabled: {
    opacity: 0.7,
    cursor: 'not-allowed',
  },
  backBtn: {
    marginTop: 12,
    fontSize: 15,
    fontWeight: 500,
    padding: '10px 24px',
    borderRadius: 12,
    border: '1px solid #ccc',
    background: '#fff',
    color: '#666',
    cursor: 'pointer',
    width: '100%',
  },
  successBanner: {
    background: '#d1fae5',
    color: '#065f46',
    fontSize: 16,
    fontWeight: 700,
    textAlign: 'center',
    borderRadius: 12,
    padding: '12px 16px',
    marginBottom: 20,
  },
  savedTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#1a1a2e',
    margin: '0 0 12px',
    overflowWrap: 'anywhere',
  },
  savedNote: {
    fontSize: 14,
    color: '#555',
    background: '#eef2ff',
    borderRadius: 10,
    padding: '10px 12px',
    margin: '0 0 16px',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
  savedContent: {
    fontSize: 16,
    lineHeight: 1.7,
    color: '#1a1a2e',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    padding: 16,
    marginBottom: 20,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },
}

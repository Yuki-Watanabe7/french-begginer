import { TutorSourceFileField } from './TutorSourceFileField'
import { TutorSourceKindPicker } from './TutorSourceKindPicker'
import { useTutorSourceForm } from '../hooks/useTutorSourceForm'
import type { SourceDocument } from '../types'
import {
  sourceAddHint,
  type ConversationInputMode,
  type SourceAddKind,
  type YoutubeInputMode,
} from '../utils/sourceIngestion'

interface Props {
  onBack: () => void
  onSaved: (source: SourceDocument) => void
}

const SOURCE_KINDS: { id: SourceAddKind; label: string }[] = [
  { id: 'manual', label: 'テキストを貼り付ける' },
  { id: 'url', label: 'Web URL' },
  { id: 'pdf', label: 'PDF' },
  { id: 'youtube', label: 'YouTube / 字幕' },
  { id: 'audio', label: '音声' },
  { id: 'conversation', label: '会話ログ / テキストファイル' },
]

const YOUTUBE_MODES: { id: YoutubeInputMode; label: string }[] = [
  { id: 'url', label: 'YouTubeのURL' },
  { id: 'subtitle', label: '字幕ファイル' },
]

const CONVERSATION_MODES: { id: ConversationInputMode; label: string }[] = [
  { id: 'text-file', label: 'テキストファイル' },
  { id: 'log', label: '会話ログ' },
]

export function TutorSourceForm({ onBack, onSaved }: Props) {
  const form = useTutorSourceForm(onSaved)
  const hint = sourceAddHint(form.kind, form.youtubeMode, form.conversationMode)
  const titleRequired = form.kind === 'manual'

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    void form.submit()
  }

  return (
    <form style={styles.container} onSubmit={handleSubmit} noValidate>
      <h2 style={styles.heading}>教材を追加</h2>
      <p style={styles.sub}>テキスト、Web、PDF、字幕、音声、会話から追加できます</p>

      <TutorSourceKindPicker
        legend="教材の種類"
        name="tutor-source-kind"
        value={form.kind}
        options={SOURCE_KINDS}
        disabled={form.isSubmitting}
        onChange={form.setKind}
      />

      {form.kind === 'youtube' && (
        <TutorSourceKindPicker
          legend="YouTubeの指定"
          name="tutor-youtube-input"
          value={form.youtubeMode}
          options={YOUTUBE_MODES}
          disabled={form.isSubmitting}
          onChange={form.setYoutubeMode}
        />
      )}

      {form.kind === 'conversation' && (
        <TutorSourceKindPicker
          legend="ファイルの種類"
          name="tutor-conversation-input"
          value={form.conversationMode}
          options={CONVERSATION_MODES}
          disabled={form.isSubmitting}
          onChange={form.setConversationMode}
        />
      )}

      {hint && <p style={styles.hint}>{hint}</p>}

      <label htmlFor="tutor-source-title" style={styles.label}>
        タイトル
        <span style={titleRequired ? styles.required : styles.optional}>
          {titleRequired ? '必須' : '任意'}
        </span>
      </label>
      <input
        id="tutor-source-title"
        style={{
          ...styles.input,
          ...(form.fieldErrors.title ? styles.inputInvalid : {}),
        }}
        type="text"
        value={form.title}
        onChange={event => form.setTitle(event.target.value)}
        placeholder={titleRequired ? '記事のタイトル、会話メモなど' : '空なら取り込み結果のタイトルを使います'}
        aria-required={titleRequired}
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

      {form.kind === 'manual' && (
        <>
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
            onChange={event => form.setContent(event.target.value)}
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
        </>
      )}

      {form.kind === 'url' && (
        <UrlField
          id="tutor-source-url"
          label="ページのURL"
          value={form.url}
          error={form.fieldErrors.url}
          disabled={form.isSubmitting}
          placeholder="https://example.com/article"
          onChange={form.setUrl}
        />
      )}

      {form.kind === 'youtube' && form.youtubeMode === 'url' && (
        <UrlField
          id="tutor-source-video"
          label="YouTubeのURL"
          value={form.video}
          error={form.fieldErrors.video}
          disabled={form.isSubmitting}
          placeholder="https://www.youtube.com/watch?v=... または動画ID"
          onChange={form.setVideo}
        />
      )}

      {form.fileSpec && (
        <TutorSourceFileField
          key={form.fileSpec.slot}
          inputId="tutor-source-file"
          accept={form.fileSpec.accept}
          file={form.file}
          error={form.fieldErrors.file}
          disabled={form.isSubmitting}
          onFile={form.setFile}
        />
      )}

      <label htmlFor="tutor-source-note" style={styles.label}>
        メモ
        <span style={styles.optional}>任意</span>
      </label>
      <textarea
        id="tutor-source-note"
        style={styles.note}
        value={form.note}
        onChange={event => form.setNote(event.target.value)}
        placeholder="どこで出会ったか、難しかったところなど"
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
        aria-busy={form.isSubmitting}
        aria-live="polite"
      >
        {form.isSubmitting ? form.pendingLabel : form.submitLabel}
      </button>
      <button type="button" style={styles.backBtn} onClick={onBack} disabled={form.isSubmitting}>
        一覧に戻る
      </button>
    </form>
  )
}

function UrlField({
  id,
  label,
  value,
  error,
  disabled,
  placeholder,
  onChange,
}: {
  id: string
  label: string
  value: string
  error?: string
  disabled: boolean
  placeholder: string
  onChange: (value: string) => void
}) {
  const errorId = `${id}-error`
  return (
    <>
      <label htmlFor={id} style={styles.label}>
        {label}
        <span style={styles.required}>必須</span>
      </label>
      <textarea
        id={id}
        style={{
          ...styles.url,
          ...(error ? styles.inputInvalid : {}),
        }}
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
        aria-required="true"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        disabled={disabled}
        rows={2}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
      />
      {error && (
        <p id={errorId} style={styles.fieldError} role="alert">
          {error}
        </p>
      )}
    </>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    textAlign: 'left',
    width: '100%',
    maxWidth: '100%',
    minWidth: 0,
    boxSizing: 'border-box',
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
  hint: {
    margin: '0 0 16px',
    color: '#555',
    fontSize: 14,
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
    maxWidth: '100%',
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
    maxWidth: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    minHeight: '40vh',
    resize: 'vertical',
    lineHeight: 1.6,
    marginBottom: 16,
  },
  url: {
    fontSize: 16,
    padding: '12px 14px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    maxWidth: '100%',
    minHeight: 72,
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    resize: 'vertical',
    lineHeight: 1.5,
    marginBottom: 16,
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  note: {
    fontSize: 16,
    padding: '12px 14px',
    borderRadius: 12,
    border: '2px solid #d0d7de',
    outline: 'none',
    width: '100%',
    maxWidth: '100%',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
    minHeight: 88,
    resize: 'vertical',
    lineHeight: 1.5,
    marginBottom: 16,
  },
  inputInvalid: {
    border: '2px solid #dc2626',
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
    overflowWrap: 'anywhere',
  },
  primaryBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '14px 0',
    minHeight: 48,
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
}

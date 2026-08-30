import { TutorCandidateList } from './TutorCandidateList'
import { useTutorSourceDetail } from '../hooks/useTutorSourceDetail'
import { formatTutorDateTime, tutorNoteFromMetadata } from '../utils/tutor'
import type { SourceDocument } from '../types'

interface Props {
  sourceId: string
  initialSource?: SourceDocument | null
  justSaved?: boolean
  onBackToList: () => void
  onAddAnother?: () => void
  onStartPractice?: () => void
}

export function TutorSourceDetail({
  sourceId,
  initialSource,
  justSaved = false,
  onBackToList,
  onAddAnother,
  onStartPractice,
}: Props) {
  const { status, source, error, retry } = useTutorSourceDetail(sourceId, initialSource)

  if (status === 'loading') {
    return (
      <div style={styles.container}>
        <p style={styles.msg} role="status">
          読み込み中...
        </p>
        <button type="button" style={styles.backBtn} onClick={onBackToList}>
          一覧に戻る
        </button>
      </div>
    )
  }

  if (status === 'not-found') {
    return (
      <div style={styles.container}>
        <div style={styles.errorBox} role="alert">
          <p style={styles.errorText}>{error ?? 'Sourceが見つかりません'}</p>
        </div>
        <button type="button" style={styles.backBtn} onClick={onBackToList}>
          一覧に戻る
        </button>
      </div>
    )
  }

  if (status === 'error' || !source) {
    return (
      <div style={styles.container}>
        <div style={styles.errorBox} role="alert">
          <p style={styles.errorText}>
            {error ?? '詳細の取得に失敗しました。通信環境を確認して再度お試しください'}
          </p>
          <button type="button" style={styles.primaryBtn} onClick={retry}>
            再試行
          </button>
        </div>
        <button type="button" style={styles.backBtn} onClick={onBackToList}>
          一覧に戻る
        </button>
      </div>
    )
  }

  const note = tutorNoteFromMetadata(source.metadata)

  return (
    <div style={styles.container}>
      {justSaved && (
        <div style={styles.successBanner} role="status">
          保存しました
        </div>
      )}
      <h2 style={styles.title}>{source.title}</h2>
      <p style={styles.meta}>{formatTutorDateTime(source.created_at)}</p>
      {note && <p style={styles.note}>{note}</p>}
      <div lang="fr" style={styles.content}>
        {source.content}
      </div>
      {onStartPractice && (
        <button type="button" style={styles.primaryBtn} onClick={onStartPractice}>
          学習する
        </button>
      )}
      <TutorCandidateList sourceId={source.id} />
      {justSaved && onAddAnother && (
        <button type="button" style={styles.primaryBtn} onClick={onAddAnother}>
          続けてテキストを追加
        </button>
      )}
      <button type="button" style={styles.backBtn} onClick={onBackToList}>
        一覧に戻る
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
  msg: {
    textAlign: 'center',
    color: '#666',
    fontSize: 16,
    margin: '24px 0',
  },
  errorBox: {
    textAlign: 'center',
    padding: 24,
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    marginBottom: 16,
  },
  errorText: {
    margin: '0 0 12px',
    color: '#444',
    fontSize: 15,
    lineHeight: 1.5,
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
  title: {
    fontSize: 20,
    fontWeight: 700,
    color: '#1a1a2e',
    margin: '0 0 8px',
    overflowWrap: 'anywhere',
    lineHeight: 1.4,
  },
  meta: {
    fontSize: 13,
    color: '#666',
    margin: '0 0 16px',
  },
  note: {
    fontSize: 14,
    color: '#555',
    background: '#eef2ff',
    borderRadius: 10,
    padding: '10px 12px',
    margin: '0 0 16px',
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    lineHeight: 1.5,
  },
  content: {
    fontSize: 16,
    lineHeight: 1.8,
    color: '#1a1a2e',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    padding: 16,
    marginBottom: 20,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
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
    marginTop: 12,
    marginBottom: 8,
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

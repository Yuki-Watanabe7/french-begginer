import { useTutorSourceList } from '../hooks/useTutorSourceList'
import { formatTutorDateTime } from '../utils/tutor'
import type { SourceSummary } from '../types'
import { TutorTodayLearningCard } from './TutorTodayLearningCard'
import { TutorTodayReviewCard } from './TutorTodayReviewCard'

interface Props {
  onSelect: (sourceId: string) => void
  onAdd: () => void
  onBack: () => void
  onStartPractice?: () => void
  onStartReview?: () => void
  onStartToday?: () => void
}

export function TutorSourceList({
  onSelect,
  onAdd,
  onBack,
  onStartPractice,
  onStartReview,
  onStartToday,
}: Props) {
  const { status, sources, error, retry } = useTutorSourceList()

  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>自分の教材</h2>
      <p style={styles.sub}>保存したフランス語テキストを読み返せます</p>

      {onStartToday && <TutorTodayLearningCard onStartToday={onStartToday} />}
      {onStartReview && <TutorTodayReviewCard onStartReview={onStartReview} />}

      {status === 'loading' && (
        <p style={styles.msg} role="status">
          読み込み中...
        </p>
      )}

      {status === 'error' && (
        <div style={styles.errorBox} role="alert">
          <p style={styles.errorText}>{error}</p>
          <button type="button" style={styles.primaryBtn} onClick={retry}>
            再試行
          </button>
        </div>
      )}

      {status === 'empty' && (
        <div style={styles.emptyBox}>
          <p style={styles.emptyTitle}>まだ保存したテキストがありません</p>
          <p style={styles.emptyHint}>読んだ文章を貼り付けて、あとから教材にできます</p>
          <button type="button" style={styles.primaryBtn} onClick={onAdd}>
            新しいテキストを追加
          </button>
        </div>
      )}

      {status === 'success' && (
        <>
          <button type="button" style={styles.primaryBtn} onClick={onAdd}>
            新しいテキストを追加
          </button>
          {onStartPractice && (
            <button type="button" style={styles.practiceBtn} onClick={onStartPractice}>
              学習する
            </button>
          )}
          <ul style={styles.list}>
            {sources.map(source => (
              <li key={source.id} style={styles.listItem}>
                <SourceRow source={source} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </>
      )}

      <button type="button" style={styles.backBtn} onClick={onBack}>
        モード選択に戻る
      </button>
    </div>
  )
}

function SourceRow({
  source,
  onSelect,
}: {
  source: SourceSummary
  onSelect: (sourceId: string) => void
}) {
  return (
    <button
      type="button"
      style={styles.row}
      onClick={() => onSelect(source.id)}
    >
      <span style={styles.rowTitle}>{source.title}</span>
      <span style={styles.rowMeta}>{formatTutorDateTime(source.created_at)}</span>
      {source.content_preview && (
        <span lang="fr" style={styles.rowPreview}>
          {source.content_preview}
        </span>
      )}
    </button>
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
  emptyBox: {
    textAlign: 'center',
    padding: 24,
    background: '#fff',
    borderRadius: 16,
    boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
    marginBottom: 16,
  },
  emptyTitle: {
    margin: '0 0 8px',
    fontSize: 16,
    fontWeight: 700,
    color: '#1a1a2e',
  },
  emptyHint: {
    margin: '0 0 20px',
    fontSize: 14,
    color: '#666',
    lineHeight: 1.5,
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
  practiceBtn: {
    fontSize: 17,
    fontWeight: 700,
    padding: '14px 0',
    minHeight: 48,
    borderRadius: 14,
    border: '2px solid #1a56d6',
    background: '#fff',
    color: '#1a56d6',
    cursor: 'pointer',
    width: '100%',
    marginTop: 12,
  },
  list: {
    listStyle: 'none',
    margin: '16px 0 0',
    padding: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  listItem: {
    margin: 0,
    padding: 0,
  },
  row: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 6,
    width: '100%',
    minHeight: 56,
    padding: '16px 18px',
    background: '#fff',
    border: '2px solid #e0e7ff',
    borderRadius: 14,
    cursor: 'pointer',
    textAlign: 'left',
    boxSizing: 'border-box',
  },
  rowTitle: {
    fontSize: 16,
    fontWeight: 700,
    color: '#1a1a2e',
    overflowWrap: 'anywhere',
    lineHeight: 1.4,
  },
  rowMeta: {
    fontSize: 13,
    color: '#666',
  },
  rowPreview: {
    fontSize: 14,
    color: '#555',
    lineHeight: 1.5,
    overflowWrap: 'anywhere',
    display: '-webkit-box',
    WebkitLineClamp: 3,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
    width: '100%',
  },
  backBtn: {
    marginTop: 16,
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

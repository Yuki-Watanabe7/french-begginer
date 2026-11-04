/** public-v1 only; independent of the learning app and its API client. */
const itemTypes = ['vocabulary', 'expression', 'grammar', 'conjugation'] as const
type ItemType = typeof itemTypes[number]

export interface PublicCard {
  card_id: string
  item_type: ItemType
  canonical_form: string
  meaning_ja: string
  explanation_ja?: string
  level?: string
}

export interface PublicSnapshot {
  schema_version: 'public-v1'
  generated_at: string
  cards: PublicCard[]
}

export class SnapshotFormatError extends Error {}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function keysAllowed(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).every(key => keys.includes(key))
}

function publicText(value: unknown, max: number): value is string {
  return typeof value === 'string' && Array.from(value).length >= 1 &&
    Array.from(value).length <= max &&
    !Array.from(value).some(ch => ch !== '\n' && /\p{Cc}/u.test(ch)) &&
    !/<[A-Za-z!/?]/.test(value) && !/\b(?:https?:\/\/|www\.)/i.test(value) &&
    !/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/.test(value) &&
    !/[A-Za-z0-9_+=-]{32,}/.test(value)
}

function validCard(value: unknown): value is PublicCard {
  return record(value) && keysAllowed(value, [
    'card_id', 'item_type', 'canonical_form', 'meaning_ja', 'explanation_ja', 'level',
  ]) && typeof value.card_id === 'string' && /^card-[0-9]{3}$/.test(value.card_id) &&
    itemTypes.some(type => type === value.item_type) &&
    publicText(value.canonical_form, 200) && publicText(value.meaning_ja, 500) &&
    (!('explanation_ja' in value) || publicText(value.explanation_ja, 2000)) &&
    (!('level' in value) || (typeof value.level === 'string' && /^[ABC][12]$/.test(value.level)))
}

function validTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) return false
  const date = new Date(value)
  return Number.isFinite(date.getTime()) && date.toISOString().replace('.000Z', 'Z') === value
}

export function parseSnapshot(value: unknown): PublicSnapshot {
  if (!record(value) || !keysAllowed(value, ['schema_version', 'generated_at', 'cards']) ||
      value.schema_version !== 'public-v1' || !validTimestamp(value.generated_at) ||
      !Array.isArray(value.cards) || value.cards.length < 1 || value.cards.length > 500 ||
      !value.cards.every(validCard) ||
      new Set(value.cards.map(card => card.card_id)).size !== value.cards.length) {
    throw new SnapshotFormatError()
  }
  return value as unknown as PublicSnapshot
}

export async function loadSnapshot(signal: AbortSignal): Promise<PublicSnapshot> {
  // Relative to this page, including a GitHub Pages repository subpath.
  const response = await fetch('./snapshot.json', {
    signal,
    cache: 'no-store',
    credentials: 'omit',
    redirect: 'error',
  })
  if (!response.ok) throw new Error('snapshot unavailable')
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new SnapshotFormatError()
  }
  return parseSnapshot(payload)
}

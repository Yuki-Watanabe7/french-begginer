/**
 * フランス語表示文生成ユーティリティ。
 *
 * elisionルール（présent現在形対象）:
 *   je + 母音始まりの活用形 → j' + 活用形  （例: je + écoute → j'écoute）
 *   je + 子音始まりの活用形 → je + スペース + 活用形（例: je + suis → je suis）
 *   その他の主語 → 主語 + スペース + 活用形
 *
 * 将来拡張:
 *   - 無音h（heure など）と有音h（hibou など）の区別は未対応（Issue #88）
 *   - me/te/se/le/la/de/ne/que のelisionは別Issueで扱う
 */

// 母音セット（アクセント付き含む）— h の扱いは将来拡張（Issue #88）
const VOWELS = new Set(['a', 'e', 'é', 'è', 'ê', 'ë', 'i', 'î', 'ï', 'o', 'ô', 'œ', 'u', 'û', 'ü', 'y'])

/**
 * 主語と活用形を結合してelisionを適用した表示文を返す。
 *
 * @param pronoun - 主語（例: "je", "tu", "il/elle"）
 * @param conjugation - 活用形のみ（例: "écoute", "suis"）— 主語付きは渡さない
 * @returns 表示文（例: "j'écoute", "je suis", "tu parles"）
 */
export function applyElision(pronoun: string, conjugation: string): string {
  if (pronoun === 'je' && conjugation.length > 0 && VOWELS.has(conjugation[0].toLowerCase())) {
    return `j'${conjugation}`
  }
  return `${pronoun} ${conjugation}`
}

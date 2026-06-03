/**
 * フランス語表示文生成（elision）のテスト。
 *
 * 責務: applyElision() が je + 母音始まり活用形を j'... に変換し、
 *       je + 子音始まり活用形を je ... にすることを保証する。
 *
 * domainデータ単体の検証（活用形の正しさ）はバックエンドの
 * test_domain_validation.py に委譲する。
 */
import { describe, it, expect } from 'vitest'
import { applyElision } from '../utils/french'

describe('applyElision', () => {
  describe('je + 母音始まり → elision (j\'...)', () => {
    it('écouter: je + écoute → j\'écoute', () => {
      expect(applyElision('je', 'écoute')).toBe("j'écoute")
    })

    it('aimer: je + aime → j\'aime', () => {
      expect(applyElision('je', 'aime')).toBe("j'aime")
    })

    it('avoir: je + ai → j\'ai', () => {
      expect(applyElision('je', 'ai')).toBe("j'ai")
    })

    it('étudier: je + étudie → j\'étudie', () => {
      expect(applyElision('je', 'étudie')).toBe("j'étudie")
    })

    it('habiter: je + habite → je habite（有音hは将来拡張、現時点はスペース結合）', () => {
      // h始まりは母音判定しない（Issue #88 将来拡張）
      expect(applyElision('je', 'habite')).toBe('je habite')
    })
  })

  describe('je + 子音始まり → スペース結合 (je ...)', () => {
    it('être: je + suis → je suis', () => {
      expect(applyElision('je', 'suis')).toBe('je suis')
    })

    it('aller: je + vais → je vais', () => {
      expect(applyElision('je', 'vais')).toBe('je vais')
    })

    it('parler: je + parle → je parle', () => {
      expect(applyElision('je', 'parle')).toBe('je parle')
    })

    it('finir: je + finis → je finis', () => {
      expect(applyElision('je', 'finis')).toBe('je finis')
    })

    it('faire: je + fais → je fais', () => {
      expect(applyElision('je', 'fais')).toBe('je fais')
    })
  })

  describe('je以外の主語 → 通常スペース結合（elisionしない）', () => {
    it('tu + parles → tu parles', () => {
      expect(applyElision('tu', 'parles')).toBe('tu parles')
    })

    it('il/elle + parle → il/elle parle', () => {
      expect(applyElision('il/elle', 'parle')).toBe('il/elle parle')
    })

    it('nous + parlons → nous parlons', () => {
      expect(applyElision('nous', 'parlons')).toBe('nous parlons')
    })

    it('vous + parlez → vous parlez', () => {
      expect(applyElision('vous', 'parlez')).toBe('vous parlez')
    })

    it('ils/elles + parlent → ils/elles parlent', () => {
      expect(applyElision('ils/elles', 'parlent')).toBe('ils/elles parlent')
    })

    it('tu + aimes → tu aimes（tu は母音始まりでもelisionしない）', () => {
      expect(applyElision('tu', 'aimes')).toBe('tu aimes')
    })
  })
})

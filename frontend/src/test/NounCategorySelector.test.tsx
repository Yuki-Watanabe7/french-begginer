import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NounCategorySelector } from '../components/NounCategorySelector'

describe('NounCategorySelector', () => {
  describe('表示', () => {
    it('全カテゴリオプションが表示される', () => {
      render(<NounCategorySelector onSelect={() => {}} onBack={() => {}} />)
      expect(screen.getByText('全名詞')).toBeInTheDocument()
      expect(screen.getByText('基本名詞')).toBeInTheDocument()
      expect(screen.getByText('食べ物')).toBeInTheDocument()
      expect(screen.getByText('場所')).toBeInTheDocument()
      expect(screen.getByText('家・生活')).toBeInTheDocument()
      expect(screen.getByText('人・家族')).toBeInTheDocument()
    })

    it('「モード選択に戻る」ボタンが表示される', () => {
      render(<NounCategorySelector onSelect={() => {}} onBack={() => {}} />)
      expect(screen.getByRole('button', { name: 'モード選択に戻る' })).toBeInTheDocument()
    })
  })

  describe('フィルタ選択', () => {
    it('「全名詞」をクリックするとonSelectが空フィルタで呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('全名詞'))
      expect(onSelect).toHaveBeenCalledWith({})
    })

    it('「基本名詞」をクリックするとonSelectが level:basic で呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('基本名詞'))
      expect(onSelect).toHaveBeenCalledWith({ level: 'basic' })
    })

    it('「食べ物」をクリックするとonSelectが category:food で呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('食べ物'))
      expect(onSelect).toHaveBeenCalledWith({ category: 'food' })
    })

    it('「場所」をクリックするとonSelectが category:place で呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('場所'))
      expect(onSelect).toHaveBeenCalledWith({ category: 'place' })
    })

    it('「家・生活」をクリックするとonSelectが category:home で呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('家・生活'))
      expect(onSelect).toHaveBeenCalledWith({ category: 'home' })
    })

    it('「人・家族」をクリックするとonSelectが category:person で呼ばれる', async () => {
      const onSelect = vi.fn()
      render(<NounCategorySelector onSelect={onSelect} onBack={() => {}} />)
      await userEvent.click(screen.getByText('人・家族'))
      expect(onSelect).toHaveBeenCalledWith({ category: 'person' })
    })
  })

  describe('戻るボタン', () => {
    it('「モード選択に戻る」をクリックするとonBackが呼ばれる', async () => {
      const onBack = vi.fn()
      render(<NounCategorySelector onSelect={() => {}} onBack={onBack} />)
      await userEvent.click(screen.getByRole('button', { name: 'モード選択に戻る' }))
      expect(onBack).toHaveBeenCalled()
    })
  })
})

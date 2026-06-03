import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VerbGroupSelector } from '../components/VerbGroupSelector'

describe('VerbGroupSelector', () => {
  it('動詞グループの4つのボタンを表示する', () => {
    render(<VerbGroupSelector onSelect={() => {}} />)

    expect(screen.getByText('全動詞')).toBeInTheDocument()
    expect(screen.getByText('-er 動詞')).toBeInTheDocument()
    expect(screen.getByText('-ir 動詞')).toBeInTheDocument()
    expect(screen.getByText('不規則動詞')).toBeInTheDocument()
  })

  it('難易度の選択肢を表示する', () => {
    render(<VerbGroupSelector onSelect={() => {}} />)

    expect(screen.getByText('基本')).toBeInTheDocument()
    expect(screen.getByText('標準')).toBeInTheDocument()
    expect(screen.getByText('応用')).toBeInTheDocument()
  })

  it('活用パターンの選択肢を表示する', () => {
    render(<VerbGroupSelector onSelect={() => {}} />)

    expect(screen.getByText('規則活用')).toBeInTheDocument()
    expect(screen.getByText('語幹変化')).toBeInTheDocument()
    expect(screen.getByText('綴り変化')).toBeInTheDocument()
    expect(screen.getByText('不規則')).toBeInTheDocument()
  })

  it('デフォルトで「全動詞」「すべて（難易度）」「すべて（パターン）」が選ばれている状態で次へを押すと正しいフィルタで呼ばれる', async () => {
    const onSelect = vi.fn()
    render(<VerbGroupSelector onSelect={onSelect} />)

    await userEvent.click(screen.getByText('次へ →'))

    expect(onSelect).toHaveBeenCalledWith({ group: 'all', level: undefined, pattern: undefined })
  })

  it('グループ・難易度・パターンを選択して次へを押すと正しいフィルタで呼ばれる', async () => {
    const onSelect = vi.fn()
    render(<VerbGroupSelector onSelect={onSelect} />)

    await userEvent.click(screen.getByText('-er 動詞'))
    await userEvent.click(screen.getByText('基本'))
    await userEvent.click(screen.getByText('規則活用'))
    await userEvent.click(screen.getByText('次へ →'))

    expect(onSelect).toHaveBeenCalledWith({ group: 'er', level: 'basic', pattern: 'regular' })
  })

  it('不規則動詞・応用・不規則パターンを選択できる', async () => {
    const onSelect = vi.fn()
    render(<VerbGroupSelector onSelect={onSelect} />)

    await userEvent.click(screen.getByText('不規則動詞'))
    await userEvent.click(screen.getByText('応用'))
    await userEvent.click(screen.getByText('不規則'))
    await userEvent.click(screen.getByText('次へ →'))

    expect(onSelect).toHaveBeenCalledWith({ group: 'irregular', level: 'challenge', pattern: 'irregular' })
  })

  it('難易度のみ選択してパターン未指定で次へを押せる', async () => {
    const onSelect = vi.fn()
    render(<VerbGroupSelector onSelect={onSelect} />)

    await userEvent.click(screen.getByText('標準'))
    await userEvent.click(screen.getByText('次へ →'))

    expect(onSelect).toHaveBeenCalledWith({ group: 'all', level: 'standard', pattern: undefined })
  })
})

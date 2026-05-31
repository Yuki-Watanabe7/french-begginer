import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VerbGroupSelector } from '../components/VerbGroupSelector'

describe('VerbGroupSelector', () => {
  it('4つの動詞グループボタンを表示する', () => {
    render(<VerbGroupSelector onSelect={() => {}} />)

    expect(screen.getByText('全動詞')).toBeInTheDocument()
    expect(screen.getByText('-er 動詞')).toBeInTheDocument()
    expect(screen.getByText('-ir 動詞')).toBeInTheDocument()
    expect(screen.getByText('不規則動詞')).toBeInTheDocument()
  })

  it('ボタンをクリックするとonSelectが対応するグループ値で呼ばれる', async () => {
    const onSelect = vi.fn()
    render(<VerbGroupSelector onSelect={onSelect} />)

    await userEvent.click(screen.getByText('全動詞'))
    expect(onSelect).toHaveBeenCalledWith('all')

    await userEvent.click(screen.getByText('-er 動詞'))
    expect(onSelect).toHaveBeenCalledWith('er')

    await userEvent.click(screen.getByText('不規則動詞'))
    expect(onSelect).toHaveBeenCalledWith('irregular')
  })
})

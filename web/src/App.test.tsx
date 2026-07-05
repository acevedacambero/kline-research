import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from './App'

describe('App', () => {
  it('shows data status and P1 audit workspace', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }) })))
    render(<App />)
    expect(await screen.findByText('数据状态')).toBeInTheDocument()
    expect(screen.getByText('P1 标签审计台')).toBeInTheDocument()
    expect(screen.getByLabelText('证券代码')).toBeInTheDocument()
  })
})

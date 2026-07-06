import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

describe('App', () => {
  afterEach(() => cleanup())
  it('shows data status and P1 audit workspace', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }) })))
    render(<App />)
    expect(await screen.findByText('数据状态')).toBeInTheDocument()
    expect(screen.getByText('P1 标签审计台')).toBeInTheDocument()
    expect(screen.getByLabelText('证券代码')).toBeInTheDocument()
    expect(screen.getByText('P2 特征审计')).toBeInTheDocument()
  })

  it('renders five P2 groups and explains unavailable history', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path.includes('/api/p2/audit')
        ? { groups: { trend: { ma60: null }, position: {}, momentum: {}, volumePrice: {}, tradingBehavior: {} }, availableHistory: 20, versions: {}, priceBasis: 'raw+qfq+total-return', reasons: [] }
        : path.includes('/api/p1/audit')
          ? { eligibility: { eligible: true, status: 'ok', reasons: [] }, entry: { status: 'normal' }, labels: {} }
          : path.includes('/bars') ? []
            : path.includes('/quality') ? { totalCached: 1 }
              : { status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }
      return { ok: true, json: async () => body }
    }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '计算并审计' }))
    expect(await screen.findByText('趋势')).toBeInTheDocument()
    expect(screen.getByText('位置')).toBeInTheDocument()
    expect(screen.getByText('动量')).toBeInTheDocument()
    expect(screen.getByText('量价')).toBeInTheDocument()
    expect(screen.getByText('交易行为')).toBeInTheDocument()
    expect(screen.getByText('历史不足')).toBeInTheDocument()
  })

  it('offers Shanghai and Shenzhen markets only', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => String(input).includes('/quality')
        ? { totalCached: 0 }
        : { status: 'ok', dataSource: 'Tencent/Sina', cachePath: 'data', versions: {} },
    })))

    const { container } = render(<App />)
    await screen.findByRole('heading', { level: 1 })
    const exchangeSelect = container.querySelector('select')

    expect(exchangeSelect).not.toBeNull()
    expect(Array.from(exchangeSelect!.options).map(option => option.value)).toEqual(['sh', 'sz'])
    expect(container.querySelector('option[value="bj"]')).toBeNull()
  })
})

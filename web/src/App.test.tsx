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
    expect(screen.getByText('P3 结构评分')).toBeInTheDocument()
    expect(screen.getAllByRole('option', { name: 'P20 可执行顺延卖出' })).toHaveLength(4)
    expect(screen.getAllByRole('option', { name: 'P5 可执行顺延卖出' })).toHaveLength(4)
  })

  it('renders five P2 groups and explains unavailable history', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path.includes('/api/p2/audit')
        ? { groups: { trend: { ma60: null }, position: {}, momentum: {}, volumePrice: {}, tradingBehavior: {} }, availableHistory: 20, versions: {}, priceBasis: 'raw+qfq+total-return', reasons: [] }
        : path.includes('/api/p3/audit')
          ? {
              availableHistory: 20,
              featureDefinitionVersion: 'daily-features-v1',
              priceBasis: 'raw+qfq+total-return',
              score: {
                version: 'p3-rule-score-v1', score: 72.5, grade: 'B', usable: true,
                reasons: [],
                components: {
                  trend: { score: 20, weight: 25, available: true, reasons: ['多头均线排列'] },
                  position: { score: 15, weight: 20, available: true, reasons: [] },
                  momentum: { score: 18, weight: 25, available: true, reasons: [] },
                  volumePrice: { score: 10, weight: 15, available: true, reasons: [] },
                  tradingBehavior: { score: 9.5, weight: 15, available: true, reasons: [] },
                },
              },
              versions: {},
            }
        : path.includes('/api/p1/audit')
          ? { eligibility: { eligible: true, status: 'ok', reasons: [] }, entry: { status: 'normal' }, labels: {} }
          : path.includes('/bars') ? []
            : path.includes('/quality') ? { totalCached: 1 }
              : { status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }
      return { ok: true, json: async () => body }
    }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '计算并审计' }))
    expect((await screen.findAllByText('趋势')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('位置').length).toBeGreaterThan(0)
    expect(screen.getAllByText('动量').length).toBeGreaterThan(0)
    expect(screen.getAllByText('量价').length).toBeGreaterThan(0)
    expect(screen.getAllByText('交易行为').length).toBeGreaterThan(0)
    expect(screen.getByText('历史不足')).toBeInTheDocument()
    expect(screen.getByText('72.5')).toBeInTheDocument()
    expect(screen.getByText(/p3-rule-score-v1/)).toBeInTheDocument()
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
    const exchangeSelect = screen.getByLabelText('交易所') as HTMLSelectElement

    expect(Array.from(exchangeSelect.options).map(option => option.value)).toEqual(['sh', 'sz'])
    expect(container.querySelector('option[value="bj"]')).toBeNull()
  })

  it('starts history backfill and renders its terminal summary', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path === '/api/datasets/import'
        ? { taskId: 'task-1', total: 5, threshold: 250 }
        : path === '/api/datasets/backfill-history/task-1'
          ? {
              status: 'completed_with_errors', done: 5, total: 5, completed: 3,
              listingHistoryShort: 1, errors: [{ security: 'sh600000' }],
              currentSecurity: null, speed: 2, etaSeconds: 0,
            }
          : path.includes('/quality')
            ? { totalCached: 5 }
            : { status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }
      return { ok: true, json: async () => body }
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: '补全短历史' }))

    expect(await screen.findByText(/已补全 3 · 新股 1 · 错误 1/)).toBeInTheDocument()
    expect(screen.getByText(/检查错误后，再手动生成 P1 和 P2/)).toBeInTheDocument()
  })

  it('starts P3 score build and polls progress', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path === '/api/scores/build'
        ? { taskId: 'score-task-1', total: 2 }
        : path === '/api/scores/tasks/score-task-1'
          ? { status: 'completed', done: 2, total: 2, rows: 520, errors: [] }
          : path.includes('/quality')
            ? { totalCached: 2 }
            : { status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }
      return { ok: true, json: async () => body }
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: '生成 P3 评分' }))

    expect(await screen.findByText(/P3 评分：2\/2，已生成 520 行/)).toBeInTheDocument()
  })

  it('runs P4 single factor validation and renders bucket metrics', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const body = path === '/api/validation/single-factor'
        ? {
            version: 'p4-single-factor-v2-independent',
            factorColumn: 'score',
            labelColumn: 'p20_executable_return',
            bucketCount: 2,
            sampleCount: 10, independentPeriodCount: 4, independenceGapDays: 7,
            rankCorrelation: 0.42,
            missingColumns: [],
            dropped: {},
            buckets: [
              { bucket: 1, count: 5, minFactor: 1, maxFactor: 50, avgFactor: 25, avgLabel: 0.01, medianLabel: 0.01, winRate: 0.6, pathSuccessRate: 0.4, avgMaxDrawdown: -0.08 },
              { bucket: 2, count: 5, minFactor: 51, maxFactor: 90, avgFactor: 70, avgLabel: 0.08, medianLabel: 0.07, winRate: 0.8, pathSuccessRate: 0.7, avgMaxDrawdown: -0.05 },
            ],
          }
        : path.includes('/quality')
          ? { totalCached: 2 }
          : { status: 'ok', dataSource: 'AkShare', cachePath: 'data', versions: {} }
      return { ok: true, json: async () => body }
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: '验证 P4 单因子' }))

    expect(await screen.findByText('p4-single-factor-v2-independent')).toBeInTheDocument()
    expect(screen.getByText('10 / 4')).toBeInTheDocument()
    expect(screen.getByText('8.00%')).toBeInTheDocument()
  })
})

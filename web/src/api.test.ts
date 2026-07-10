import { describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('API errors', () => {
  it('surfaces the backend detail message instead of a generic status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: { code: 'AKSHARE_FETCH_FAILED', message: '行情获取失败：上游断开' } }),
    })))
    await expect(api.bars('sh', '601100')).rejects.toThrow('行情获取失败：上游断开')
  })

  it('uses the P2 build and P2/P3 audit endpoints', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.buildFeatures('all')
    await api.featureAudit('sh', '600000', '2024-01-02')
    await api.scoreAudit('sh', '600000', '2024-01-02')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/features/build')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/p2/audit')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/p3/audit')
  })

  it('uses the history backfill start and status endpoints', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.startHistoryBackfill()
    await api.historyBackfillTask('task-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/datasets/import')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', body: '{"scope":"history_backfill"}' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/datasets/backfill-history/task-1')
  })
})

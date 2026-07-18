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

  it('uses the P3 score build and task endpoints', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.buildScores('all')
    await api.scoreTask('task-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/scores/build')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/scores/tasks/task-1')
  })

  it('uses the P4 single factor validation endpoint', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.validateSingleFactor()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/validation/single-factor')
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

  it('posts configurable windows to the drift monitor endpoint', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.runDriftMonitor(40, 180)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/monitoring/drift')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: '{"recent_days":40,"reference_days":180}',
    })
  })

  it('promotes a registered model through the lifecycle endpoint', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.promoteModel('abc123')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/model/p7/registry/abc123/promote')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' })
  })

  it('loads the consolidated research acceptance report', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.researchAcceptance()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/system/research-acceptance')
  })

  it('starts the snapshot-aware P1-P3 research pipeline', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.buildResearchPipeline('stale')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/pipeline/research/build')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: '{"scope":"stale"}',
    })
  })

  it('starts the five-stage daily research maintenance pipeline', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.buildDailyPipeline('changed')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/pipeline/daily/build')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: '{"scope":"changed"}',
    })
  })

  it('plans and executes safe artifact cleanup', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.planArtifactCleanup()
    await api.executeArtifactCleanup('a'.repeat(64), 'quarantine')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/system/artifact-cleanup/plan')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/system/artifact-cleanup/execute')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ plan_id: 'a'.repeat(64), mode: 'quarantine' }),
    })
  })

  it('downloads and checksum-confirms deletion of a server backup', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    const name = 'kline-data-20260718T010203Z.tar.gz'
    const sha256 = 'a'.repeat(64)
    expect(api.backupDownloadUrl(name)).toBe(`/api/system/backups/${name}/download`)
    await api.deleteBackup(name, sha256)
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/system/backups/${name}?sha256=${sha256}`)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'DELETE' })
  })

  it('requests cooperative cancellation through the generic task endpoint', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetchMock)
    await api.cancelTask('task with space')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks/task%20with%20space')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'DELETE' })
  })
})
